using System;
using System.IO;
using Xunit;
using HelixSRSwapper;

namespace Tests;

public class DetectReEngineTests : IDisposable
{
    private readonly string _tempFolder;

    public DetectReEngineTests()
    {
        _tempFolder = Path.Combine(Path.GetTempPath(), "HelixSR_DetectReEngine_" + Guid.NewGuid().ToString());
        Directory.CreateDirectory(_tempFolder);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempFolder))
        {
            Directory.Delete(_tempFolder, true);
        }
    }

    [Fact]
    public void DetectReEngine_NullOrEmptyFolder_ReturnsFalse()
    {
        // Act & Assert
        Assert.False(Engine.DetectReEngine(null, new GameInfo()));
        Assert.False(Engine.DetectReEngine(string.Empty, new GameInfo()));
    }

    [Fact]
    public void DetectReEngine_NonExistentFolder_ReturnsFalse()
    {
        // Arrange
        string fakeFolder = Path.Combine(_tempFolder, "DoesNotExist");

        // Act
        bool result = Engine.DetectReEngine(fakeFolder, new GameInfo());

        // Assert
        Assert.False(result);
    }

    [Fact]
    public void DetectReEngine_EmptyFolder_ReturnsFalse()
    {
        // Act
        bool result = Engine.DetectReEngine(_tempFolder, new GameInfo());

        // Assert
        Assert.False(result);
    }

    [Fact]
    public void DetectReEngine_StorageFolderPresent_ReturnsTrue()
    {
        // Arrange
        Directory.CreateDirectory(Path.Combine(_tempFolder, "_storage_"));

        // Act
        bool result = Engine.DetectReEngine(_tempFolder, new GameInfo());

        // Assert
        Assert.True(result);
    }

    [Fact]
    public void DetectReEngine_ReChunkPakFilePresent_ReturnsTrue()
    {
        // Arrange
        File.WriteAllText(Path.Combine(_tempFolder, "re_chunk_000.pak"), "dummy data");

        // Act
        bool result = Engine.DetectReEngine(_tempFolder, new GameInfo());

        // Assert
        Assert.True(result);
    }

    [Fact]
    public void DetectReEngine_ReDlcPakFilePresent_ReturnsTrue()
    {
        // Arrange
        File.WriteAllText(Path.Combine(_tempFolder, "re_chunk_999.pak"), "dummy data");

        // Act
        bool result = Engine.DetectReEngine(_tempFolder, new GameInfo());

        // Assert
        Assert.True(result);
    }
}
