using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Globalization;

namespace Evolution;
public sealed record Intent(string Id, long Ticks, string Digest);
public static partial class Policy
{
    [GeneratedRegex(@"\A[a-z0-9][a-z0-9-]{0,63}\z", RegexOptions.CultureInvariant)]
    private static partial Regex Identity();
    public static Intent Validate(int consumer, string id, uint? version, int? capability, int? unit, long amount, bool? confirmed)
    {
        if (!Identity().IsMatch(id))
            throw new ArgumentException("IDENTITY");
        long ticks;
        if (version == 1 && capability == 1 && unit == 1)
            ticks = amount;
        else if (consumer == 2 && version == 2 && capability == 2 && unit == 2 && confirmed == true && amount % 1000 == 0)
            ticks = amount / 1000;
        else
            throw new ArgumentException("SEMANTIC_CAPABILITY_DENIED");
        if (ticks is < 1 or > 1_000_000)
            throw new ArgumentException("AMOUNT_BOUND");
        var digest = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes($"effect-v1\n{id}\nTICKS\n{ticks.ToString(CultureInfo.InvariantCulture)}\n")));
        return new Intent(id, ticks, digest);
    }
}

public sealed record Outcome(string Status, string Id, string Result = "", string Detail = "");
