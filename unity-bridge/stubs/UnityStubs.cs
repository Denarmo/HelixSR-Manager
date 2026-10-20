// Minimal stand-ins for the UnityEngine / BepInEx APIs the bridge uses, so `mcs` can check that the plugin compiles.
// Not a Unity replacement: nothing here runs. Compile check: see unity-bridge/README.md.
using System;
namespace BepInEx { public class BepInPlugin : Attribute { public BepInPlugin(string a, string b, string c) { } }
  public class Logger { public void LogInfo(object o) { } }
  public class BaseUnityPlugin : UnityEngine.MonoBehaviour { public BepInEx.Logger Logger = new BepInEx.Logger(); public BepInEx.Configuration.ConfigFile Config = new BepInEx.Configuration.ConfigFile(); } }
namespace BepInEx.Configuration { public class ConfigEntry<T> { public T Value; }
  public class ConfigFile { public ConfigEntry<T> Bind<T>(string s, string k, T d, string desc) { return new ConfigEntry<T> { Value = d }; } } }
namespace UnityEngine {
  public class Object { public string name; }
  public class Component : Object { public string tag; public T[] GetComponents<T>() { return new T[0]; } }
  public class Behaviour : Component { public bool enabled; }
  public class MonoBehaviour : Behaviour { }
  public enum RenderingPath { Forward }
  public struct Matrix4x4 { public float m02, m12; }
  public enum CameraType { Game }
  [Flags] public enum DepthTextureMode { None = 0, Depth = 1, MotionVectors = 4 }
  public enum FilterMode { Bilinear }
  public static class QualitySettings { public static int antiAliasing; }
  public static class Mathf { public static int Clamp(int v, int a, int b) { return v < a ? a : v > b ? b : v; } }
  public enum RenderTextureFormat { ARGB32 }
  public class Texture : Object { public IntPtr GetNativeTexturePtr() { return IntPtr.Zero; } public FilterMode filterMode; }
  public class RenderTexture : Texture { public int width, height, antiAliasing; public RenderTexture(int w, int h, int d, RenderTextureFormat f) { width = w; height = h; } public void Create() { } public void Release() { } public static implicit operator bool(RenderTexture r) { return r != null; } }
  public class Camera : Behaviour { public static Camera[] allCameras; public static int allCamerasCount; public float depth; public int pixelWidth, pixelHeight; public RenderingPath actualRenderingPath; public bool allowMSAA, allowHDR; public Rendering.CommandBuffer[] GetCommandBuffers(Rendering.CameraEvent e) { return null; } public static Camera main; public static event Action<Camera> onPreCull, onPostRender;
    public CameraType cameraType; public RenderTexture targetTexture; public DepthTextureMode depthTextureMode; public Matrix4x4 projectionMatrix, nonJitteredProjectionMatrix; public bool useJitteredProjectionMatrixForTransparentRendering;
    public void ResetProjectionMatrix() { } public static bool operator ==(Camera a, Camera b) { return object.ReferenceEquals(a, b); } public static bool operator !=(Camera a, Camera b) { return !object.ReferenceEquals(a, b); }
    public override bool Equals(object o) { return base.Equals(o); } public override int GetHashCode() { return 0; } }
  public static class Screen { public static int width, height; }
  public static class Shader { public static void SetGlobalFloat(string n, float v) { } public static Texture GetGlobalTexture(string n) { return null; } }
  public static class Graphics { public static void Blit(Texture s, RenderTexture d) { } public static void ExecuteCommandBuffer(Rendering.CommandBuffer c) { } }
}
namespace UnityEngine.Rendering { public enum CameraEvent { BeforeForwardOpaque, AfterEverything } public class CommandBuffer { public string name; public void Clear() { } public void Release() { } public void IssuePluginEventAndData(IntPtr f, int id, IntPtr d) { } } }
