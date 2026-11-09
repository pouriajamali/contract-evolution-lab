using System.Globalization;
using System.Reflection;
using System.Net;
using System.Text.Json;
using Evolution;
using Evolution.Wire;
using Grpc.Core;
using Microsoft.AspNetCore.Server.Kestrel.Core;
using Microsoft.Extensions.Logging;
#if V2
const int Version = 2;
#else
const int Version = 1;
#endif
try
{
    if (args.Length == 1 && args[0] is "--help" or "--version")
    {
        Console.WriteLine(JsonSerializer.Serialize(new {version=Version,source=Assembly.GetExecutingAssembly().GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion,usage="Synthetic literal-loopback gRPC consumer; serve PORT | init | expand | backfill BATCH | contract ack-old-writers-stopped | rollback ack-new-writers-stopped | oracle"}));return 0;
    }
    if (args.Length >= 1 && args[0] == "serve")
    {
        if (args.Length != 2 || !int.TryParse(args[1],out var port) || port is < 1024 or > 65535) throw new ArgumentException("PORT");
        var builder = WebApplication.CreateSlimBuilder(new WebApplicationOptions {Args=Array.Empty<string>(),ContentRootPath=AppContext.BaseDirectory,EnvironmentName=Environments.Production});
        builder.Configuration.Sources.Clear();
        builder.Logging.ClearProviders();
        builder.WebHost.ConfigureKestrel(options=>{options.Limits.MaxRequestBodySize=16384;options.Limits.MaxConcurrentConnections=16;options.Limits.MaxRequestHeadersTotalSize=8192;options.Limits.Http2.MaxStreamsPerConnection=8;options.Listen(IPAddress.Loopback,port,l=>l.Protocols=HttpProtocols.Http2);});
        builder.Services.AddSingleton<Store>();
        builder.Services.AddGrpc(options=>{options.MaxReceiveMessageSize=16384;options.MaxSendMessageSize=16384;options.EnableDetailedErrors=false;});
        var app=builder.Build();app.MapGrpcService<ActionService>(); await app.RunAsync();return 0;
    }
    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10)); var store=new Store(); object output;
    if (args.SequenceEqual(new[]{"init"})) {await store.Init(timeout.Token);output=new {status="INITIALIZED_FRESH"};}
    else if (args.SequenceEqual(new[]{"oracle"})) output=await store.Oracle(timeout.Token);
    else if (args.Length is 1 or 2 && args[0] is "expand" or "backfill" or "contract" or "rollback")
    {
        if (args[0]=="contract" && (args.Length!=2 || args[1]!="ack-old-writers-stopped")) throw new ArgumentException("STOP_OLD_WRITERS_FIRST");
        if (args[0]=="rollback" && (args.Length!=2 || args[1]!="ack-new-writers-stopped")) throw new ArgumentException("STOP_NEW_WRITERS_FIRST");
        var batch=args[0]=="backfill" && args.Length==2 ? int.Parse(args[1],CultureInfo.InvariantCulture):0;
        output=new {status=await store.Migrate(args[0],batch,timeout.Token)};
    }
    else throw new ArgumentException("USAGE");
    Console.WriteLine(JsonSerializer.Serialize(output));return 0;
}
catch (Exception error) when (error is ArgumentException or FormatException or OverflowException or Npgsql.NpgsqlException or OperationCanceledException or IOException)
{
    Console.WriteLine(JsonSerializer.Serialize(new {status="FAILED_CLOSED",error=error.GetType().Name}));return 2;
}
public sealed class ActionService(Store store) : SyntheticActionsService.SyntheticActionsServiceBase
{
    private static readonly SemaphoreSlim Slots = new(8,8);
    public override async Task<ApplyResponse> Apply(ApplyRequest request,ServerCallContext context)
    {
        using var timeout=CancellationTokenSource.CreateLinkedTokenSource(context.CancellationToken);timeout.CancelAfter(TimeSpan.FromSeconds(6));
        if (!await Slots.WaitAsync(0,timeout.Token)) return new(){Status="BUSY",OperationId=request.OperationId};
        try
        {
#if V2
            const int consumer=2; bool? confirmed=request.HasConfirmed?request.Confirmed:null;
#else
            const int consumer=1; bool? confirmed=null;
#endif
            var intent=Policy.Validate(consumer,request.OperationId,request.HasSemanticVersion?request.SemanticVersion:null,request.HasCapability?(int)request.Capability:null,request.HasUnit?(int)request.Unit:null,request.Amount,confirmed);
            var outcome=await store.Apply(consumer,intent,timeout.Token);
            return new(){Status=outcome.Status,OperationId=outcome.Id,Result=outcome.Result,Detail=outcome.Detail};
        }
        catch (ArgumentException) {return new(){Status="DENIED",OperationId=request.OperationId};}
        catch (Exception error) when(error is Npgsql.NpgsqlException or OperationCanceledException or IOException or OverflowException)
        {return new(){Status="UNKNOWN",OperationId=request.OperationId,Detail="Resolve with the SAME business identity and canonical intent; never invent a retry identity."};}
        finally {Slots.Release();}
    }
}
