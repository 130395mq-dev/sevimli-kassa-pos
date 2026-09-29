// Test-only native process; never shipped as the POS. Exercises real process
// startup/crash/readiness behavior without a database, UI, printer or network.
using System;
using System.IO;
using System.Diagnostics;
using System.Threading;
public class Stub {
  public static int Main(string[] args) {
    string home = AppDomain.CurrentDomain.BaseDirectory;
    string mode = File.ReadAllText(Path.Combine(home, "mode.txt")).Trim();
    if (args.Length == 2 && args[0] == "--check-runtime") {
      Directory.CreateDirectory(args[1]);
      File.WriteAllText(Path.Combine(args[1], "result.json"), "{\"ok\":true,\"frozen\":true,\"integrity\":\"ok\"}");
      return mode == "runtime-bad" ? 1 : 0;
    }
    string appdata = Environment.GetEnvironmentVariable("APPDATA");
    string state = Path.Combine(appdata, "SevimliKassa", "update");
    Directory.CreateDirectory(state);
    File.AppendAllText(Path.Combine(state, "launches.txt"), mode + " " + Process.GetCurrentProcess().Id + "\n");
    if (mode == "crash") return 3;
    if (mode == "ready") {
      string nonce = Environment.GetEnvironmentVariable("SEVIMLI_UPDATE_NONCE") ?? "";
      File.WriteAllText(Path.Combine(state, "run-ready.json"), "{\"pid\":" + Process.GetCurrentProcess().Id + ",\"version\":\"9.0.0\",\"nonce\":\"" + nonce + "\"}");
    }
    Thread.Sleep(15000);
    return 0;
  }
}
