using System;
using System.IO;
using NUnit.Framework;
using HelixSRSwapper;

namespace Tests
{
    [TestFixture]
    public class EngineTests
    {
        private string tempTestFolder;
        private string testIniPath;

        [SetUp]
        public void Setup()
        {
            tempTestFolder = Path.Combine(Path.GetTempPath(), "HelixSRTest_" + Guid.NewGuid().ToString());
            Directory.CreateDirectory(tempTestFolder);
            testIniPath = Path.Combine(tempTestFolder, "OptiScaler.ini");
        }

        [TearDown]
        public void Teardown()
        {
            if (Directory.Exists(tempTestFolder))
            {
                Directory.Delete(tempTestFolder, true);
            }
        }

        [Test]
        public void ReadOptiScalerIni_FileExists_ReturnsContent()
        {
            // Arrange
            string expectedContent = "[Settings]\nEnable=true";
            File.WriteAllText(testIniPath, expectedContent);

            // Act
            string actualContent = Engine.ReadOptiScalerIni(tempTestFolder);

            // Assert
            Assert.That(actualContent, Is.EqualTo(expectedContent));
        }

        [Test]
        public void ReadOptiScalerIni_FileDoesNotExist_ReturnsEmptyString()
        {
            // Act
            string actualContent = Engine.ReadOptiScalerIni(tempTestFolder);

            // Assert
            Assert.That(actualContent, Is.EqualTo(""));
        }

        [Test]
        public void SaveOptiScalerIni_ValidContent_CreatesFileWithContent()
        {
            // Arrange
            string contentToSave = "[Settings]\nEnable=false";

            // Act
            Engine.SaveOptiScalerIni(tempTestFolder, contentToSave);

            // Assert
            Assert.That(File.Exists(testIniPath), Is.True);
            string readContent = File.ReadAllText(testIniPath);
            Assert.That(readContent, Is.EqualTo(contentToSave));
        }
    }
}
