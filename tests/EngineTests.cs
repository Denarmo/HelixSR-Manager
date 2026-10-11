using System;
using System.IO;
using NUnit.Framework;
using HelixSRSwapper;

namespace Tests
{
    public class EngineTests
    {
        private string tempDir;

        [SetUp]
        public void SetUp()
        {
            tempDir = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
            Directory.CreateDirectory(tempDir);
        }

        [TearDown]
        public void TearDown()
        {
            if (Directory.Exists(tempDir))
            {
                Directory.Delete(tempDir, true);
            }
        }

        [Test]
        public void ReadGameLog_ReturnsLogContent_WhenLogExistsInHelixSrFolder()
        {
            string helixSrDir = Path.Combine(tempDir, "HelixSR");
            Directory.CreateDirectory(helixSrDir);

            string logName = "test.log";
            string logPath = Path.Combine(helixSrDir, logName);
            string expectedContent = "Log content in HelixSR folder";
            File.WriteAllText(logPath, expectedContent);

            string result = Engine.ReadGameLog(tempDir, logName);

            Assert.AreEqual(expectedContent, result);
        }

        [Test]
        public void ReadGameLog_ReturnsLogContent_WhenLogExistsInGameFolder()
        {
            string logName = "test.log";
            string logPath = Path.Combine(tempDir, logName);
            string expectedContent = "Log content in game folder";
            File.WriteAllText(logPath, expectedContent);

            string result = Engine.ReadGameLog(tempDir, logName);

            Assert.AreEqual(expectedContent, result);
        }

        [Test]
        public void ReadGameLog_ReturnsNoLogContent_WhenLogDoesNotExist()
        {
            string logName = "nonexistent.log";

            string result = Engine.ReadGameLog(tempDir, logName);

            Assert.AreEqual("No log content found.", result);
        }

        [Test]
        public void ReadGameLog_PrioritizesHelixSrFolderLog()
        {
            string helixSrDir = Path.Combine(tempDir, "HelixSR");
            Directory.CreateDirectory(helixSrDir);

            string logName = "test.log";
            string helixLogPath = Path.Combine(helixSrDir, logName);
            string helixContent = "Log content in HelixSR folder";
            File.WriteAllText(helixLogPath, helixContent);

            string gameLogPath = Path.Combine(tempDir, logName);
            string gameContent = "Log content in game folder";
            File.WriteAllText(gameLogPath, gameContent);

            string result = Engine.ReadGameLog(tempDir, logName);

            Assert.AreEqual(helixContent, result);
        }
    }
}
