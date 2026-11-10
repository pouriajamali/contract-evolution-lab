using System.Globalization;
using Npgsql;

namespace Evolution;
public sealed class Store
{
    private readonly string connection;
    public Store()
    {
        var raw = Environment.GetEnvironmentVariable("EVOLUTION_LAB_DB") ?? throw new ArgumentException("LAB_DATABASE_REQUIRED");
        var builder = new NpgsqlConnectionStringBuilder(raw);
        if (builder.Host != "127.0.0.1" || builder.Database != "contract_lab" || builder.Username != "contract_lab" || builder.Port < 1024 || string.IsNullOrWhiteSpace(builder.Password))
            throw new ArgumentException("DEDICATED_LOOPBACK_DATABASE_REQUIRED");
        builder.Timeout = 3;
        builder.CommandTimeout = 3;
        builder.Pooling = false;
        builder.IncludeErrorDetail = false;
        connection = builder.ConnectionString;
    }

    private Task<NpgsqlConnection> Open(CancellationToken token) => OpenOwned(new NpgsqlConnection(connection), static (db, cancellation) => db.OpenAsync(cancellation), token);
    internal static async Task<T> OpenOwned<T>(T resource, Func<T, CancellationToken, Task> open, CancellationToken token)
        where T : class, IAsyncDisposable
    {
        try
        {
            await open(resource, token);
            return resource;
        }
        catch
        {
            try
            {
                await resource.DisposeAsync();
            }
            catch
            {
            // Cleanup must not replace the original open failure or cancellation.
            }

            throw;
        }
    }

    private static async Task<object?> Scalar(NpgsqlConnection db, NpgsqlTransaction? tx, string sql, CancellationToken token, params (string, object)[] values)
    {
        await using var cmd = new NpgsqlCommand(sql, db, tx);
        foreach (var(key, value)in values)
            cmd.Parameters.AddWithValue(key, value);
        return await cmd.ExecuteScalarAsync(token);
    }

    public async Task Init(CancellationToken token)
    {
        await using var db = await Open(token);
        await using var tx = await db.BeginTransactionAsync(token);
        await Scalar(db, tx, "CREATE SCHEMA evolution_v1", token);
        await Scalar(db, tx, "CREATE TABLE evolution_v1.state (id boolean PRIMARY KEY CHECK(id), stage integer NOT NULL CHECK(stage BETWEEN 0 AND 2), total bigint NOT NULL CHECK(total>=0), effects integer NOT NULL CHECK(effects BETWEEN 0 AND 4096), backfilled bigint NOT NULL CHECK(backfilled>=0))", token);
        await Scalar(db, tx, "INSERT INTO evolution_v1.state VALUES (true,0,0,0,0)", token);
        await Scalar(db, tx, "CREATE TABLE evolution_v1.effects (operation_id text PRIMARY KEY, request_hash text NOT NULL, amount_ticks bigint NOT NULL CHECK(amount_ticks BETWEEN 1 AND 1000000), receipt text NOT NULL)", token);
        await tx.CommitAsync(token);
    }

    private static async Task<int> Stage(NpgsqlConnection db, NpgsqlTransaction tx, CancellationToken token) => Convert.ToInt32(await Scalar(db, tx, "SELECT stage FROM evolution_v1.state WHERE id FOR UPDATE", token), CultureInfo.InvariantCulture);
    public async Task<Outcome> Apply(int version, Intent intent, CancellationToken token)
    {
        await using var db = await Open(token);
        await using var tx = await db.BeginTransactionAsync(token);
        var stage = await Stage(db, tx, token);
        if (version == 1 && stage == 2)
            return new("SCHEMA_UNSUPPORTED", intent.Id);
        await using (var get = new NpgsqlCommand("SELECT request_hash,receipt FROM evolution_v1.effects WHERE operation_id=@id", db, tx))
        {
            get.Parameters.AddWithValue("id", intent.Id);
            await using var reader = await get.ExecuteReaderAsync(token);
            if (await reader.ReadAsync(token))
                return reader.GetString(0) == intent.Digest ? new("REPLAY", intent.Id, reader.GetString(1)) : new("CONFLICT", intent.Id);
        }

        var count = Convert.ToInt32(await Scalar(db, tx, "SELECT effects FROM evolution_v1.state WHERE id", token), CultureInfo.InvariantCulture);
        if (count >= 4096)
            return new("CAPACITY_REJECTED", intent.Id);
        var total = Convert.ToInt64(await Scalar(db, tx, "SELECT total FROM evolution_v1.state WHERE id", token), CultureInfo.InvariantCulture);
        var next = checked(total + intent.Ticks);
        var result = next.ToString(CultureInfo.InvariantCulture);
        if (stage == 0 || version == 1)
        {
            // A v1 writer never names or supplies the expanded column. The database
            // compatibility trigger alone fills it during stage 1.
            await Scalar(db, tx, "INSERT INTO evolution_v1.effects(operation_id,request_hash,amount_ticks,receipt) VALUES(@id,@hash,@ticks,@receipt)", token, ("id", intent.Id), ("hash", intent.Digest), ("ticks", intent.Ticks), ("receipt", result));
        }
        else if (stage == 1)
            await Scalar(db, tx, "INSERT INTO evolution_v1.effects(operation_id,request_hash,amount_ticks,amount_scaled,receipt) VALUES(@id,@hash,@ticks,@scaled,@receipt)", token, ("id", intent.Id), ("hash", intent.Digest), ("ticks", intent.Ticks), ("scaled", checked(intent.Ticks * 1000)), ("receipt", result));
        else if (stage == 2)
            await Scalar(db, tx, "INSERT INTO evolution_v1.effects(operation_id,request_hash,amount_scaled,receipt) VALUES(@id,@hash,@scaled,@receipt)", token, ("id", intent.Id), ("hash", intent.Digest), ("scaled", checked(intent.Ticks * 1000)), ("receipt", result));
        else
            throw new InvalidOperationException("STAGE");
        await Scalar(db, tx, "UPDATE evolution_v1.state SET total=@total,effects=effects+1 WHERE id", token, ("total", next));
        await Pause("before-commit", token);
        await tx.CommitAsync(token);
        await Pause("after-commit", token);
        return new("APPLIED", intent.Id, result);
    }

    private static async Task Pause(string stage, CancellationToken token)
    {
        if (Environment.GetEnvironmentVariable("EVOLUTION_LAB_PAUSE") != stage)
            return;
        var dir = Environment.GetEnvironmentVariable("EVOLUTION_LAB_HOOK_DIR") ?? throw new ArgumentException("HOOK_DIR");
        Directory.CreateDirectory(dir);
        await File.WriteAllTextAsync(Path.Combine(dir, "ready"), stage, token);
        using var bound = CancellationTokenSource.CreateLinkedTokenSource(token);
        bound.CancelAfter(TimeSpan.FromSeconds(20));
        while (!File.Exists(Path.Combine(dir, "resume")))
            await Task.Delay(20, bound.Token);
    }

    public async Task<string> Migrate(string action, int batch, CancellationToken token)
    {
        await using var db = await Open(token);
        await using var tx = await db.BeginTransactionAsync(token);
        var stage = await Stage(db, tx, token);
        switch (action)
        {
            case "expand":
                if (stage != 0)
                    return "WRONG_STAGE";
                await Scalar(db, tx, "ALTER TABLE evolution_v1.effects ADD COLUMN amount_scaled bigint CHECK(amount_scaled BETWEEN 1000 AND 1000000000)", token);
                await Scalar(db, tx, "CREATE FUNCTION evolution_v1.dual_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.amount_scaled IS NULL THEN NEW.amount_scaled := NEW.amount_ticks*1000; END IF; IF NEW.amount_scaled<>NEW.amount_ticks*1000 THEN RAISE EXCEPTION 'UNIT_INVARIANT'; END IF; RETURN NEW; END $$", token);
                await Scalar(db, tx, "CREATE TRIGGER dual_write BEFORE INSERT OR UPDATE ON evolution_v1.effects FOR EACH ROW EXECUTE FUNCTION evolution_v1.dual_write()", token);
                await Scalar(db, tx, "UPDATE evolution_v1.state SET stage=1 WHERE id", token);
                break;
            case "backfill":
                if (stage != 1)
                    return "WRONG_STAGE";
                if (batch is < 1 or > 32)
                    throw new ArgumentException("BATCH_BOUND");
                var changed = Convert.ToInt64(await Scalar(db, tx, "WITH selected AS (SELECT operation_id FROM evolution_v1.effects WHERE amount_scaled IS NULL ORDER BY operation_id LIMIT @batch FOR UPDATE), updated AS (UPDATE evolution_v1.effects SET amount_scaled=amount_ticks*1000 WHERE operation_id IN (SELECT operation_id FROM selected) RETURNING 1) SELECT count(*) FROM updated", token, ("batch", batch)), CultureInfo.InvariantCulture);
                await Scalar(db, tx, "UPDATE evolution_v1.state SET backfilled=backfilled+@n WHERE id", token, ("n", changed));
                await tx.CommitAsync(token);
                return "BACKFILLED:" + changed.ToString(CultureInfo.InvariantCulture);
            case "contract":
                if (stage != 1)
                    return "WRONG_STAGE";
                if (Convert.ToInt64(await Scalar(db, tx, "SELECT count(*) FROM evolution_v1.effects WHERE amount_scaled IS NULL OR amount_scaled<>amount_ticks*1000", token), CultureInfo.InvariantCulture) != 0)
                    return "INVARIANT_NOT_READY";
                await Scalar(db, tx, "DROP TRIGGER dual_write ON evolution_v1.effects", token);
                await Scalar(db, tx, "DROP FUNCTION evolution_v1.dual_write()", token);
                await Scalar(db, tx, "ALTER TABLE evolution_v1.effects ALTER COLUMN amount_scaled SET NOT NULL", token);
                await Scalar(db, tx, "ALTER TABLE evolution_v1.effects DROP COLUMN amount_ticks", token);
                await Scalar(db, tx, "UPDATE evolution_v1.state SET stage=2 WHERE id", token);
                break;
            case "rollback":
                if (stage == 2)
                    return "ROLLBACK_BLOCKED";
                if (stage != 1)
                    return "WRONG_STAGE";
                await Scalar(db, tx, "DROP TRIGGER dual_write ON evolution_v1.effects", token);
                await Scalar(db, tx, "DROP FUNCTION evolution_v1.dual_write()", token);
                await Scalar(db, tx, "ALTER TABLE evolution_v1.effects DROP COLUMN amount_scaled", token);
                await Scalar(db, tx, "UPDATE evolution_v1.state SET stage=0 WHERE id", token);
                break;
            default:
                throw new ArgumentException("UNKNOWN_MIGRATION");
        }

        await tx.CommitAsync(token);
        return action.ToUpperInvariant() + "_COMMITTED";
    }

    public async Task<object> Oracle(CancellationToken token)
    {
        await using var db = await Open(token);
        await using var tx = await db.BeginTransactionAsync(token);
        var stage = await Stage(db, tx, token);
        var stateJson = (string)(await Scalar(db, tx, "SELECT row_to_json(s)::text FROM evolution_v1.state s", token) ?? throw new InvalidOperationException());
        var rowsJson = (string)(await Scalar(db, tx, "SELECT COALESCE(json_agg(e ORDER BY operation_id),'[]'::json)::text FROM evolution_v1.effects e", token) ?? throw new InvalidOperationException());
        await tx.CommitAsync(token);
        return new
        {
            stage,
            state = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(stateJson),
            effects = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(rowsJson)
        };
    }
}
