using System;
using System.IO;
using System.Windows;

namespace HelixSRSwapper
{
    public static class Program
    {
        [STAThread]
        public static void Main(string[] args)
        {
            try
            {
                // Prevent the process or any spawned child process (explorer.exe, powershell.exe, etc.)
                // from holding an OS directory lock on the application folder.
                string tempDir = Path.GetTempPath();
                if (Directory.Exists(tempDir))
                {
                    Environment.CurrentDirectory = tempDir;
                }
            }
            catch { }

            try
            {
                var app = new Application
                {
                    ShutdownMode = ShutdownMode.OnMainWindowClose
                };
                var win = new MainWindow();
                app.Run(win);
            }
            finally
            {
                Environment.Exit(0);
            }
        }
    }
}
