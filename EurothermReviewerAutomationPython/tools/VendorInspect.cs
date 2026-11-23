using System;
using System.Linq;
using System.Reflection;
using System.Runtime.Loader;
class Program {
 static void Main(string[] args) {
  const string dir=@"C:\Program Files\Eurotherm\Eurotherm Reviewer\ReviewerService";
  AssemblyLoadContext.Default.Resolving += (ctx,name)=>{var p=System.IO.Path.Combine(dir,name.Name+".dll");return System.IO.File.Exists(p)?ctx.LoadFromAssemblyPath(p):null;};
  var a=AssemblyLoadContext.Default.LoadFromAssemblyPath(System.IO.Path.Combine(dir,"Eurotherm.Data.dll"));
  if(args.Length>0 && args[0]=="read") {
   var iface=a.GetType("Eurotherm.Data.Uhh.IUhhDataConsumer");
   var make=typeof(DispatchProxy).GetMethods().Single(m=>m.Name=="Create"&&m.IsGenericMethodDefinition);
   var consumer=make.MakeGenericMethod(iface,typeof(ConsumerProxy)).Invoke(null,null);
   var importer=Activator.CreateInstance(a.GetType("Eurotherm.Data.Uhh.UhhFileImporter"));
   var logasm=AssemblyLoadContext.Default.LoadFromAssemblyPath(System.IO.Path.Combine(dir,"log4net.dll"));
   var logger=logasm.GetType("log4net.LogManager").GetMethod("GetLogger",new[]{typeof(Type)}).Invoke(null,new object[]{typeof(Program)});
   importer.GetType().GetMethod("SetLogger").Invoke(importer,new[]{logger});
   using var stream=System.IO.File.Open(args[1],System.IO.FileMode.Open,System.IO.FileAccess.Read,System.IO.FileShare.Read);
   using var br=new System.IO.BinaryReader(stream);
   importer.GetType().GetMethod("ReadUhhFile").Invoke(importer,new[]{br,(object)args[1],consumer});
   var cp=(ConsumerProxy)consumer;
   Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new {cp.FirstSample,cp.LastSample,cp.Samples,cp.Records}));
   return;
  }
  foreach(var t in a.GetTypes().Where(t=>new[]{"UhhRecordReader","UhhArchiveStream"}.Any(n=>t.Name==n) || t.GetMethods().Any(m=>m.Name=="ReadUhhFile"))) {
   Console.WriteLine("TYPE "+t.FullName);
   foreach(var c in t.GetConstructors())Console.WriteLine("CTOR "+c);
   foreach(var m in t.GetMethods(BindingFlags.Public|BindingFlags.Instance|BindingFlags.Static))Console.WriteLine("METHOD "+m);
   foreach(var f in t.GetFields(BindingFlags.Public|BindingFlags.Instance|BindingFlags.Static))Console.WriteLine("FIELD "+f);
  }
 }
}
public class ConsumerProxy:DispatchProxy {
 public DateTimeOffset? FirstSample,LastSample;
 public int Samples;
 public System.Collections.Generic.List<object> Records=new();
 private System.Collections.Generic.Dictionary<string,object> props=new();
 protected override object Invoke(MethodInfo method,object[] args) {
  if(method.Name.StartsWith("get_"))return props.TryGetValue(method.Name[4..],out var v)?v:(method.ReturnType.IsValueType?Activator.CreateInstance(method.ReturnType):null);
  if(method.Name.StartsWith("set_")){props[method.Name[4..]]=args[0];return null;}
  if(args.Length>0 && args[0]!=null) {
   var rec=args[0];var t=rec.GetType();var ts=t.GetProperty("Timestamp");
   if(ts!=null && ts.GetValue(rec) is DateTimeOffset stamp && method.Name is "SampleDataRecord" or "ReferenceDataRecord") {
    FirstSample=FirstSample==null||stamp<FirstSample?stamp:FirstSample;LastSample=LastSample==null||stamp>LastSample?stamp:LastSample;Samples++;
   }
   if(method.Name is "StartRecord" or "EndRecord" or "HistoryRecord" or "SegmentRecord" or "BatchStartRecord" or "BatchHeaderRecord" or "BatchStopRecord") {
    var details=t.GetProperties().Where(p=>p.CanRead&&p.GetIndexParameters().Length==0).ToDictionary(p=>p.Name,p=>p.GetValue(rec)?.ToString());
    Records.Add(new {kind=method.Name,details});
   }
  }
  return method.ReturnType==typeof(void)?null:method.ReturnType==typeof(bool)?true:method.ReturnType.IsValueType?Activator.CreateInstance(method.ReturnType):null;
 }
}
