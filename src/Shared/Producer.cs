using System.Globalization;
using System.Reflection;
using System.Text.Json;
using Evolution.Wire;
using Google.Protobuf;
using Grpc.Core;
using Grpc.Net.Client;
#if V2
const int Version=2;
#else
const int Version=1;
#endif
try
{
    if (args.Length==1 && args[0] is "--help" or "--version")
    {Console.WriteLine(JsonSerializer.Serialize(new {version=Version,source=Assembly.GetExecutingAssembly().GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion,usage="Synthetic literal-loopback producer: encode CASE ID TICKS NEWFILE | call http://127.0.0.1:PORT FILE | bridge binary|json IN NEWOUT | inspect FILE"}));return 0;}
    byte[] Read(string path)
    {
        using var stream=File.OpenRead(path);var buffer=new byte[16385];var count=stream.ReadAtLeast(buffer,buffer.Length,throwOnEndOfStream:false);if(count>16384)throw new ArgumentException("FRAME_BOUND");return buffer[..count];
    }
    void Write(string path,byte[] bytes){if(bytes.Length>16384)throw new ArgumentException("FRAME_BOUND");using var file=new FileStream(path,FileMode.CreateNew);file.Write(bytes);}
    if(args.Length==5 && args[0]=="encode")
    {
        var ticks=long.Parse(args[3],CultureInfo.InvariantCulture);
        var request=new ApplyRequest{OperationId=args[2],SemanticVersion=1,Capability=(Capability)1,Unit=(Unit)1,Amount=ticks};
        switch(args[1])
        {
            case "legacy":break;
            case "additive":
#if V2
                request.Memo="synthetic-additive-note";
#endif
                break;
            case "missing":request.ClearCapability();break;
            case "unknown":request.Capability=(Capability)99;break;
            case "guarded":
            case "unsafe":
                request.SemanticVersion=2;request.Capability=(Capability)2;request.Unit=(Unit)2;request.Amount=checked(ticks*1000);
#if V2
                if(args[1]=="guarded") request.Confirmed=true;
#endif
                break;
            default:throw new ArgumentException("CASE");
        }
        Write(args[4],request.ToByteArray());Console.WriteLine(JsonSerializer.Serialize(new{status="ENCODED",version=Version,bytes=request.CalculateSize()}));return 0;
    }
    if(args.Length==4 && args[0]=="bridge")
    {
        var input=ApplyRequest.Parser.ParseFrom(Read(args[2]));
        var output=args[1] switch {"binary"=>input,"json"=>JsonParser.Default.Parse<ApplyRequest>(JsonFormatter.Default.Format(input)),_=>throw new ArgumentException("MODE")};
        Write(args[3],output.ToByteArray());Console.WriteLine(JsonSerializer.Serialize(new{status="BRIDGED",version=Version,mode=args[1]}));return 0;
    }
    if(args.Length==2 && args[0]=="inspect")
    {
        var r=ApplyRequest.Parser.ParseFrom(Read(args[1]));
#if V2
        bool? confirmed=r.HasConfirmed?r.Confirmed:null;string? memo=r.HasMemo?r.Memo:null;
#else
        bool? confirmed=null;string? memo=null;
#endif
        Console.WriteLine(JsonSerializer.Serialize(new{version=Version,id=r.OperationId,semantic=r.HasSemanticVersion?(uint?)r.SemanticVersion:null,capability=r.HasCapability?(int?)r.Capability:null,unit=r.HasUnit?(int?)r.Unit:null,amount=r.Amount.ToString(CultureInfo.InvariantCulture),confirmed,memo}));return 0;
    }
    if(args.Length==3 && args[0]=="call")
    {
        if(!Uri.TryCreate(args[1],UriKind.Absolute,out var uri) || uri.Scheme!="http" || uri.Host!="127.0.0.1" || uri.Port<1024 || uri.AbsolutePath!="/" || uri.UserInfo!="" || uri.Query!="" || uri.Fragment!="")throw new ArgumentException("LITERAL_LOOPBACK_REQUIRED");
        var request=ApplyRequest.Parser.ParseFrom(Read(args[2]));
        using var handler=new SocketsHttpHandler{UseProxy=false,AllowAutoRedirect=false,ConnectTimeout=TimeSpan.FromSeconds(2)};
        using var channel=GrpcChannel.ForAddress(uri,new GrpcChannelOptions{HttpHandler=handler,MaxReceiveMessageSize=16384,MaxSendMessageSize=16384});
        try
        {
            var result=await new SyntheticActionsService.SyntheticActionsServiceClient(channel).ApplyAsync(request,deadline:DateTime.UtcNow.AddSeconds(8));
            Console.WriteLine(JsonSerializer.Serialize(new{status=result.Status,id=result.OperationId,result=result.Result,detail=result.Detail}));return 0;
        }
        catch(RpcException)
        {Console.WriteLine(JsonSerializer.Serialize(new{status="UNKNOWN",id=request.OperationId,detail="Resolve only with the SAME identity and intent."}));return 4;}
    }
    throw new ArgumentException("USAGE");
}
catch(Exception error) when(error is ArgumentException or FormatException or IOException or OverflowException or InvalidProtocolBufferException)
{Console.WriteLine(JsonSerializer.Serialize(new{status="FAILED_CLOSED",error=error.GetType().Name}));return 2;}
