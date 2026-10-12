using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Threading;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
using System.Diagnostics;
using System.Runtime.InteropServices;
using FolderBrowserDialog = System.Windows.Forms.FolderBrowserDialog;
using Application = System.Windows.Application;
using Button = System.Windows.Controls.Button;
using ComboBox = System.Windows.Controls.ComboBox;
using HorizontalAlignment = System.Windows.HorizontalAlignment;
using Label = System.Windows.Controls.Label;
using ListBox = System.Windows.Controls.ListBox;
using ListView = System.Windows.Controls.ListView;
using MessageBox = System.Windows.MessageBox;
using Orientation = System.Windows.Controls.Orientation;
using Path = System.IO.Path;
using TextBox = System.Windows.Controls.TextBox;

namespace HelixSRSwapper
{
    [StructLayout(LayoutKind.Sequential)]
    public struct XINPUT_GAMEPAD
    {
        public ushort wButtons;
        public byte bLeftTrigger;
        public byte bRightTrigger;
        public short sThumbLX;
        public short sThumbLY;
        public short sThumbRX;
        public short sThumbRY;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct XINPUT_STATE
    {
        public uint dwPacketNumber;
        public XINPUT_GAMEPAD Gamepad;
    }

    internal static class XInputButtons
    {
        public const ushort DPAD_UP = 0x0001;
        public const ushort DPAD_DOWN = 0x0002;
        public const ushort DPAD_LEFT = 0x0004;
        public const ushort DPAD_RIGHT = 0x0008;
        public const ushort START = 0x0010;
        public const ushort BACK = 0x0020;
        public const ushort LEFT_THUMB = 0x0040;
        public const ushort RIGHT_THUMB = 0x0080;
        public const ushort LEFT_SHOULDER = 0x0100;
        public const ushort RIGHT_SHOULDER = 0x0200;
        public const ushort A = 0x1000;
        public const ushort B = 0x2000;
        public const ushort X = 0x4000;
        public const ushort Y = 0x8000;
    }

    internal static class XInputNative
    {
        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
        private static extern IntPtr LoadLibrary(string lpFileName);

        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
        private static extern IntPtr GetProcAddress(IntPtr hModule, string lpProcName);

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        public delegate int XInputGetStateDelegate(int dwUserIndex, ref XINPUT_STATE pState);

        private static XInputGetStateDelegate _getState;
        private static bool _initialized = false;
        private static bool _available = false;

        public static bool IsAvailable
        {
            get
            {
                EnsureInitialized();
                return _available;
            }
        }

        private static void EnsureInitialized()
        {
            if (_initialized) return;
            _initialized = true;
            string[] dlls = new string[] { "xinput1_4.dll", "xinput9_1_0.dll", "xinput1_3.dll" };
            foreach (var dll in dlls)
            {
                try
                {
                    IntPtr hMod = LoadLibrary(dll);
                    if (hMod != IntPtr.Zero)
                    {
                        IntPtr proc = GetProcAddress(hMod, "XInputGetState");
                        if (proc != IntPtr.Zero)
                        {
                            _getState = (XInputGetStateDelegate)Marshal.GetDelegateForFunctionPointer(proc, typeof(XInputGetStateDelegate));
                            _available = true;
                            break;
                        }
                    }
                }
                catch { }
            }
        }

        public static int GetState(int userIndex, ref XINPUT_STATE state)
        {
            EnsureInitialized();
            if (_getState != null)
            {
                try
                {
                    return _getState(userIndex, ref state);
                }
                catch { }
            }
            return 1167; // ERROR_DEVICE_NOT_CONNECTED
        }
    }

    public class MainWindow : Window
    {
        // Theme State (DLSS5-Swapper Aurora Dark & Clean Light)
        private bool _isLightTheme = false;

        private Brush BgApp;
        private Brush BgSidebar;
        private Brush BgCard;
        private Brush BgCardHover;
        private Brush BgSurface2;
        private Brush BorderColor;
        private Brush BorderStrong;
        private Brush AccentEmerald;
        private Brush AccentEmeraldStrong;
        private Brush AccentEmeraldBg;
        private Brush AccentBlue;
        private Brush AccentSky;
        private Brush AccentViolet;
        private Brush AccentAmber;
        private Brush AccentRed;
        private Brush TextMain;
        private Brush TextMuted;
        private Brush TextDim;
        private Brush TextOnAccent;

        // State
        private List<GameInfo> _allGames = new List<GameInfo>();
        private List<string> _customFolders = new List<string>();
        private GameInfo _selectedGame = null;
        private string _currentTab = "games";
        private string _quickFilter = "all";
        private bool _isGridView = true;
        private Process _compileProc = null;
        private volatile bool _isClosing = false;

        // Handheld & Controller Navigation State
        private bool _isHandheldMode = false;
        private WindowStyle _prevWindowStyle = WindowStyle.SingleBorderWindow;
        private WindowState _prevWindowState = WindowState.Normal;
        private ResizeMode _prevResizeMode = ResizeMode.CanResize;
        private Grid _rootGrid;
        private Border _handheldLegendBar;
        private Button _btnHandheldToggle;
        private DispatcherTimer _gamepadTimer;
        private int _focusedGameIndex = -1;
        private int _gamepadNavHoldCount = 0;
        private int _lastNavDirection = 0;
        private ushort _prevGamepadButtons = 0;
        private byte _prevLeftTrigger = 0;
        private byte _prevRightTrigger = 0;
        private List<GameInfo> _currentRenderedGames = new List<GameInfo>();

        // UI Controls
        private TextBlock _txtGameCountBadge;
        private Ellipse _dotCoreStatus;
        private Ellipse _dotSidebarCardStatus;
        private TextBlock _txtSidebarCardStatus;
        private Border _barSidebarProgress;
        private TextBox _txtSearch;
        private TextBlock _txtSearchPlaceholder;
        private ComboBox _cmbLauncher;
        private ComboBox _cmbStatus;
        private ComboBox _cmbSort;
        private WrapPanel _gridWrapPanel;
        private ListView _listGamesView;
        private ScrollViewer _gamesScrollViewer;
        private Border _emptyStatePanel;
        private Grid _drawerPanel;
        private Border _dropOverlay;
        private Border _toastBanner;
        private TextBlock _txtToastMessage;
        private DispatcherTimer _toastTimer;

        // Quick Filter Pill Buttons & Counters
        private Dictionary<string, Button> _filterPillButtons = new Dictionary<string, Button>();
        private TextBlock _txtStatTotal;
        private TextBlock _txtStatActive;
        private TextBlock _txtStatDirect;
        private TextBlock _txtStatOpti;

        // Drawer Controls
        private TextBlock _txtDrawerTitle;
        private Image _imgDrawerThumb;
        private Border _bannerDrawerHero;
        private Image _imgDrawerHero;
        private TextBlock _txtDrawerPlatform;
        private TextBlock _txtDrawerRoute;
        private TextBlock _txtDrawerStatus;
        private ComboBox _cmbDrawerInstallMethod;
        private TextBlock _txtDrawerMethodHint;
        private StackPanel _panelDrawerFg;
        private ComboBox _cmbDrawerFgMode;
        private System.Windows.Controls.CheckBox _chkDrawerFakeNvapi;
        private System.Windows.Controls.CheckBox _chkDrawerReFramework;
        private bool _updatingDrawerControls = false;
        private Button _btnDrawerInstall;
        private Button _btnDrawerUninstall;
        private TextBlock _txtDrawerExe;
        private TextBlock _txtDrawerFolder;
        private TextBlock _txtDrawerInputs;
        private TextBlock _txtDrawerMethod;
        private TextBlock _txtDrawerGuide;
        private TextBox _txtIniEditor;
        private TextBox _txtLogOutput;
        private TextBlock _txtGpuFooter;

        // Drawer Segmented Pill Tabs
        private Border _drawerTabGuidePane;
        private Border _drawerTabIniPane;
        private Border _drawerTabLogsPane;
        private Button _btnDrawerTabGuide;
        private Button _btnDrawerTabIni;
        private Button _btnDrawerTabLogs;
        private string _currentDrawerTab = "guide";

        // Engine Tab Controls
        private TextBlock _txtWeightsStatus;
        private TextBlock _txtWeightsSize;
        private TextBlock _txtKernelsSize;
        private TextBlock _txtToolchainStatus;
        private ComboBox _cmbDlssSource;
        private System.Windows.Controls.CheckBox _chkWave64;
        private TextBox _txtCompileConsole;
        private Button _btnStartBuild;

        // Navigation Panes
        private Grid _paneGames;
        private Grid _paneCore;
        private Grid _paneMyFsr;
        private Grid _paneSettings;
        private Grid _paneAbout;

        private Button _navBtnGames;
        private Button _navBtnCore;
        private Button _navBtnMyFsr;
        private Button _navBtnSettings;
        private Button _navBtnAbout;
        private Dictionary<string, Ellipse> _navDots = new Dictionary<string, Ellipse>();

        public MainWindow()
        {
            try
            {
                ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072 | (SecurityProtocolType)768 | SecurityProtocolType.Ssl3;
            }
            catch { }

            Title = string.Format("HelixSR Manager v{0} — Neural Upscaler & Game Manager", Engine.AppVersion);
            Width = 1320;
            Height = 850;
            MinWidth = 1020;
            MinHeight = 660;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            AllowDrop = true;
            try { Icon = CreateAppLogoIcon(); } catch { }

            DragEnter += MainWindow_DragEnter;
            DragLeave += MainWindow_DragLeave;
            Drop += MainWindow_Drop;
            PreviewKeyDown += MainWindow_PreviewKeyDown;

            LoadSettings();
            ApplyThemePalette();
            ApplyCustomControlResources();
            BuildUi();
            Loaded += MainWindow_Loaded;
        }

        private static ImageSource CreateAppLogoIcon()
        {
            int size = 64;
            var visual = new DrawingVisual();
            using (DrawingContext dc = visual.RenderOpen())
            {
                var bgBrush = new LinearGradientBrush(
                    Color.FromRgb(241, 196, 15),
                    Color.FromRgb(243, 156, 18),
                    new Point(0, 0),
                    new Point(1, 1));
                var borderPen = new Pen(new SolidColorBrush(Color.FromArgb(95, 255, 255, 255)), 2.0);
                dc.DrawRoundedRectangle(bgBrush, borderPen, new Rect(2, 2, size - 4, size - 4), 15, 15);

                // Lightning bolt geometry matching sidebar logo
                var boltGeom = Geometry.Parse("M 36,10 L 16,35 L 30,35 L 25,54 L 48,28 L 34,28 Z");
                var shadowBrush = new SolidColorBrush(Color.FromArgb(65, 0, 0, 0));
                dc.PushTransform(new TranslateTransform(1.5, 2.0));
                dc.DrawGeometry(shadowBrush, null, boltGeom);
                dc.Pop();

                var boltBrush = new SolidColorBrush(Color.FromRgb(10, 12, 16));
                dc.DrawGeometry(boltBrush, new Pen(boltBrush, 1.2) { LineJoin = PenLineJoin.Round }, boltGeom);
            }

            var bmp = new RenderTargetBitmap(size, size, 96, 96, PixelFormats.Pbgra32);
            bmp.Render(visual);
            bmp.Freeze();
            return bmp;
        }

        private void ApplyThemePalette()
        {
            if (_isLightTheme)
            {
                BgApp = new SolidColorBrush(Color.FromRgb(238, 241, 245));
                BgSidebar = new SolidColorBrush(Color.FromRgb(255, 255, 255));
                BgCard = new SolidColorBrush(Color.FromRgb(247, 249, 252));
                BgCardHover = new SolidColorBrush(Color.FromRgb(234, 239, 246));
                BgSurface2 = new SolidColorBrush(Color.FromRgb(241, 245, 249));
                BorderColor = new SolidColorBrush(Color.FromArgb(32, 15, 23, 42));
                BorderStrong = new SolidColorBrush(Color.FromArgb(140, 212, 172, 13));
                AccentEmerald = new SolidColorBrush(Color.FromRgb(212, 172, 13));
                AccentEmeraldStrong = new SolidColorBrush(Color.FromRgb(241, 196, 15));
                AccentEmeraldBg = new SolidColorBrush(Color.FromArgb(38, 241, 196, 15));
                AccentBlue = new SolidColorBrush(Color.FromRgb(2, 132, 199));
                AccentSky = new SolidColorBrush(Color.FromRgb(14, 165, 233));
                AccentViolet = new SolidColorBrush(Color.FromRgb(124, 58, 237));
                AccentAmber = new SolidColorBrush(Color.FromRgb(217, 119, 6));
                AccentRed = new SolidColorBrush(Color.FromRgb(220, 38, 38));
                TextMain = new SolidColorBrush(Color.FromRgb(24, 31, 41));
                TextMuted = new SolidColorBrush(Color.FromRgb(88, 101, 119));
                TextDim = new SolidColorBrush(Color.FromRgb(133, 146, 164));
                TextOnAccent = new SolidColorBrush(Color.FromRgb(10, 12, 16));
            }
            else
            {
                // HelixSR Manager Signature Dark Gold Palette (#06080d base, #11161e panels, #f1c40f gold accent, #39d5ff cyan)
                BgApp = new SolidColorBrush(Color.FromRgb(6, 8, 13));
                BgSidebar = new SolidColorBrush(Color.FromRgb(17, 22, 30));
                BgCard = new SolidColorBrush(Color.FromRgb(22, 28, 38));
                BgCardHover = new SolidColorBrush(Color.FromRgb(30, 39, 53));
                BgSurface2 = new SolidColorBrush(Color.FromRgb(13, 17, 24));
                BorderColor = new SolidColorBrush(Color.FromArgb(26, 255, 255, 255));
                BorderStrong = new SolidColorBrush(Color.FromArgb(145, 241, 196, 15));
                AccentEmerald = new SolidColorBrush(Color.FromRgb(241, 196, 15));
                AccentEmeraldStrong = new SolidColorBrush(Color.FromRgb(241, 196, 15));
                AccentEmeraldBg = new SolidColorBrush(Color.FromArgb(38, 241, 196, 15));
                AccentBlue = new SolidColorBrush(Color.FromRgb(57, 213, 255));
                AccentSky = new SolidColorBrush(Color.FromRgb(56, 189, 248));
                AccentViolet = new SolidColorBrush(Color.FromRgb(155, 107, 255));
                AccentAmber = new SolidColorBrush(Color.FromRgb(245, 158, 11));
                AccentRed = new SolidColorBrush(Color.FromRgb(239, 68, 68));
                TextMain = new SolidColorBrush(Color.FromRgb(243, 246, 251));
                TextMuted = new SolidColorBrush(Color.FromRgb(154, 166, 184));
                TextDim = new SolidColorBrush(Color.FromRgb(104, 116, 136));
                TextOnAccent = new SolidColorBrush(Color.FromRgb(10, 12, 16));
            }
            Background = BgApp;
        }

        private void ApplyCustomControlResources()
        {
            string bgSurface = _isLightTheme ? "#FFFFFF" : "#161C26";
            string bgHover = _isLightTheme ? "#EAEFF6" : "#222C3C";
            string bgPopup = _isLightTheme ? "#FFFFFF" : "#12171F";
            string borderHex = _isLightTheme ? "#D0D7E2" : "#2E3A4E";
            string fgMain = _isLightTheme ? "#181F29" : "#F3F6FB";
            string fgMuted = _isLightTheme ? "#586577" : "#9AA6B8";
            string accentHex = _isLightTheme ? "#D4AC0D" : "#F1C40F";
            string accentSelBg = _isLightTheme ? "#26F1C40F" : "#28F1C40F";

            string xaml = @"
<ResourceDictionary xmlns=""http://schemas.microsoft.com/winfx/2006/xaml/presentation""
                    xmlns:x=""http://schemas.microsoft.com/winfx/2006/xaml"">

    <ControlTemplate x:Key=""ModernComboBoxToggleButton"" TargetType=""ToggleButton"">
        <Border x:Name=""Border"" Background=""" + bgSurface + @""" BorderBrush=""" + borderHex + @""" BorderThickness=""1"" CornerRadius=""8"">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition />
                    <ColumnDefinition Width=""28"" />
                </Grid.ColumnDefinitions>
                <Path Grid.Column=""1"" HorizontalAlignment=""Center"" VerticalAlignment=""Center"" Data=""M 0 0 L 4.5 4.5 L 9 0 Z"" Fill=""" + fgMuted + @""" />
            </Grid>
        </Border>
        <ControlTemplate.Triggers>
            <Trigger Property=""IsMouseOver"" Value=""True"">
                <Setter TargetName=""Border"" Property=""Background"" Value=""" + bgHover + @""" />
                <Setter TargetName=""Border"" Property=""BorderBrush"" Value=""" + accentHex + @""" />
            </Trigger>
            <Trigger Property=""IsChecked"" Value=""True"">
                <Setter TargetName=""Border"" Property=""BorderBrush"" Value=""" + accentHex + @""" />
            </Trigger>
        </ControlTemplate.Triggers>
    </ControlTemplate>

    <Style TargetType=""{x:Type ComboBox}"">
        <Setter Property=""Foreground"" Value=""" + fgMain + @""" />
        <Setter Property=""Background"" Value=""" + bgSurface + @""" />
        <Setter Property=""BorderBrush"" Value=""" + borderHex + @""" />
        <Setter Property=""BorderThickness"" Value=""1"" />
        <Setter Property=""ScrollViewer.HorizontalScrollBarVisibility"" Value=""Auto"" />
        <Setter Property=""ScrollViewer.VerticalScrollBarVisibility"" Value=""Auto"" />
        <Setter Property=""Template"">
            <Setter.Value>
                <ControlTemplate TargetType=""ComboBox"">
                    <Grid>
                        <ToggleButton Name=""ToggleButton"" Template=""{StaticResource ModernComboBoxToggleButton}"" Focusable=""false"" IsChecked=""{Binding Path=IsDropDownOpen,Mode=TwoWay,RelativeSource={RelativeSource TemplatedParent}}"" ClickMode=""Press"" />
                        <ContentPresenter Name=""ContentSite"" IsHitTestVisible=""False"" Content=""{TemplateBinding SelectionBoxItem}"" ContentTemplate=""{TemplateBinding SelectionBoxItemTemplate}"" ContentTemplateSelector=""{TemplateBinding ItemTemplateSelector}"" Margin=""12,4,28,4"" VerticalAlignment=""Center"" HorizontalAlignment=""Left"" />
                        <Popup Name=""Popup"" Placement=""Bottom"" IsOpen=""{TemplateBinding IsDropDownOpen}"" AllowsTransparency=""True"" Focusable=""False"" PopupAnimation=""Slide"">
                            <Grid Name=""DropDown"" SnapsToDevicePixels=""True"" MinWidth=""{TemplateBinding ActualWidth}"" MaxHeight=""{TemplateBinding MaxDropDownHeight}"">
                                <Border x:Name=""DropDownBorder"" Background=""" + bgPopup + @""" BorderThickness=""1"" BorderBrush=""" + borderHex + @""" CornerRadius=""8"" Margin=""0,4,0,0"" Padding=""4"" />
                                <ScrollViewer Margin=""4,8,4,4"" SnapsToDevicePixels=""True"">
                                    <StackPanel IsItemsHost=""True"" KeyboardNavigation.DirectionalNavigation=""Contained"" />
                                </ScrollViewer>
                            </Grid>
                        </Popup>
                    </Grid>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <Style TargetType=""{x:Type ComboBoxItem}"">
        <Setter Property=""Foreground"" Value=""" + fgMain + @""" />
        <Setter Property=""Background"" Value=""Transparent"" />
        <Setter Property=""Padding"" Value=""10,7"" />
        <Setter Property=""Cursor"" Value=""Hand"" />
        <Setter Property=""Template"">
            <Setter.Value>
                <ControlTemplate TargetType=""ComboBoxItem"">
                    <Border x:Name=""Bd"" Background=""{TemplateBinding Background}"" CornerRadius=""6"" Padding=""{TemplateBinding Padding}"" Margin=""1"">
                        <ContentPresenter />
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property=""IsHighlighted"" Value=""True"">
                            <Setter TargetName=""Bd"" Property=""Background"" Value=""" + bgHover + @""" />
                        </Trigger>
                        <Trigger Property=""IsSelected"" Value=""True"">
                            <Setter TargetName=""Bd"" Property=""Background"" Value=""" + accentSelBg + @""" />
                            <Setter Property=""Foreground"" Value=""" + accentHex + @""" />
                            <Setter Property=""FontWeight"" Value=""SemiBold"" />
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <Style TargetType=""{x:Type ContextMenu}"">
        <Setter Property=""SnapsToDevicePixels"" Value=""True"" />
        <Setter Property=""OverridesDefaultStyle"" Value=""True"" />
        <Setter Property=""Grid.IsSharedSizeScope"" Value=""true"" />
        <Setter Property=""HasDropShadow"" Value=""True"" />
        <Setter Property=""Template"">
            <Setter.Value>
                <ControlTemplate TargetType=""ContextMenu"">
                    <Border Name=""Border"" Background=""" + bgPopup + @""" BorderBrush=""" + borderHex + @""" BorderThickness=""1"" CornerRadius=""10"" Padding=""5"">
                        <StackPanel IsItemsHost=""True"" KeyboardNavigation.DirectionalNavigation=""Cycle"" />
                    </Border>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <Style TargetType=""{x:Type MenuItem}"">
        <Setter Property=""Foreground"" Value=""" + fgMain + @""" />
        <Setter Property=""FontSize"" Value=""12"" />
        <Setter Property=""Cursor"" Value=""Hand"" />
        <Setter Property=""Template"">
            <Setter.Value>
                <ControlTemplate TargetType=""MenuItem"">
                    <Border x:Name=""Bd"" Background=""Transparent"" CornerRadius=""6"" Padding=""12,7"" Margin=""1"">
                        <ContentPresenter ContentSource=""Header"" RecognizesAccessKey=""True"" />
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property=""IsHighlighted"" Value=""True"">
                            <Setter TargetName=""Bd"" Property=""Background"" Value=""" + bgHover + @""" />
                            <Setter Property=""Foreground"" Value=""" + accentHex + @""" />
                        </Trigger>
                        <Trigger Property=""IsEnabled"" Value=""False"">
                            <Setter Property=""Opacity"" Value=""0.45"" />
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <Style x:Key=""PillButtonStyle"" TargetType=""{x:Type Button}"">
        <Setter Property=""Template"">
            <Setter.Value>
                <ControlTemplate TargetType=""Button"">
                    <Border x:Name=""BtnBorder"" Background=""{TemplateBinding Background}"" BorderBrush=""{TemplateBinding BorderBrush}"" BorderThickness=""{TemplateBinding BorderThickness}"" CornerRadius=""9"" Padding=""{TemplateBinding Padding}"">
                        <ContentPresenter HorizontalAlignment=""{TemplateBinding HorizontalContentAlignment}"" VerticalAlignment=""{TemplateBinding VerticalContentAlignment}"" />
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property=""IsMouseOver"" Value=""True"">
                            <Setter TargetName=""BtnBorder"" Property=""Opacity"" Value=""0.92"" />
                            <Setter TargetName=""BtnBorder"" Property=""BorderBrush"" Value=""" + accentHex + @""" />
                        </Trigger>
                        <Trigger Property=""IsPressed"" Value=""True"">
                            <Setter TargetName=""BtnBorder"" Property=""Opacity"" Value=""0.78"" />
                        </Trigger>
                        <Trigger Property=""IsEnabled"" Value=""False"">
                            <Setter TargetName=""BtnBorder"" Property=""Opacity"" Value=""0.45"" />
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>

    <Style x:Key=""SidebarNavButtonStyle"" TargetType=""{x:Type Button}"">
        <Setter Property=""Template"">
            <Setter.Value>
                <ControlTemplate TargetType=""Button"">
                    <Border x:Name=""NavBorder"" Background=""{TemplateBinding Background}"" BorderBrush=""{TemplateBinding BorderBrush}"" BorderThickness=""{TemplateBinding BorderThickness}"" CornerRadius=""12"" Padding=""{TemplateBinding Padding}"">
                        <ContentPresenter HorizontalAlignment=""Stretch"" VerticalAlignment=""Center"" />
                    </Border>
                    <ControlTemplate.Triggers>
                        <Trigger Property=""IsMouseOver"" Value=""True"">
                            <Setter TargetName=""NavBorder"" Property=""BorderBrush"" Value=""" + borderHex + @""" />
                        </Trigger>
                    </ControlTemplate.Triggers>
                </ControlTemplate>
            </Setter.Value>
        </Setter>
    </Style>
</ResourceDictionary>";

            try
            {
                Resources = (ResourceDictionary)XamlReader.Parse(xaml);
            }
            catch { }
        }

        private void ToggleTheme()
        {
            _isLightTheme = !_isLightTheme;
            SaveSettings();
            var prevGame = _selectedGame;
            var prevTab = _currentTab;
            var prevSearch = _txtSearch != null ? _txtSearch.Text : "";

            ApplyThemePalette();
            ApplyCustomControlResources();
            BuildUi();

            if (!string.IsNullOrEmpty(prevSearch) && _txtSearch != null)
            {
                _txtSearch.Text = prevSearch;
            }

            UpdateCoreStatus();
            UpdateGpuInfo();
            _txtGameCountBadge.Text = _allGames.Count.ToString();
            FilterGames();
            UpdateDlssCandidates();
            SwitchTab(prevTab);

            if (prevGame != null)
            {
                OpenDrawer(prevGame);
            }

            ShowToast(_isLightTheme ? "Switched to Clean Light Theme" : "Switched to HelixSR Manager Dark Gold Theme");
        }

        protected override void OnClosed(EventArgs e)
        {
            _isClosing = true;
            if (_gamepadTimer != null)
            {
                try { _gamepadTimer.Stop(); _gamepadTimer = null; } catch { }
            }
            KillCompileProcess();
            base.OnClosed(e);
            try { Application.Current.Shutdown(); } catch { }
            Environment.Exit(0);
        }

        private void KillCompileProcess()
        {
            var proc = Interlocked.Exchange(ref _compileProc, null);
            if (proc == null) return;
            try
            {
                if (!proc.HasExited)
                {
                    try
                    {
                        using (var tk = Process.Start(new ProcessStartInfo
                        {
                            FileName = "taskkill.exe",
                            Arguments = string.Format("/F /T /PID {0}", proc.Id),
                            CreateNoWindow = true,
                            UseShellExecute = false,
                            WorkingDirectory = Path.GetTempPath()
                        }))
                        {
                            if (tk != null) tk.WaitForExit(2000);
                        }
                    }
                    catch { }
                    try { if (!proc.HasExited) proc.Kill(); } catch { }
                }
            }
            catch { }
            finally
            {
                try { proc.Dispose(); } catch { }
            }
        }

        private static void OpenFolderInExplorer(string folderPath)
        {
            if (string.IsNullOrEmpty(folderPath) || !Directory.Exists(folderPath)) return;
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = folderPath,
                    UseShellExecute = true,
                    Verb = "open"
                });
            }
            catch { }
        }

        private void MainWindow_Loaded(object sender, RoutedEventArgs e)
        {
            RefreshGames();
            UpdateCoreStatus();
            UpdateGpuInfo();

            // Detect handheld mode (Windows Xbox Mode / Full Screen Experience or SteamOS / Bazzite)
            try
            {
                var handheldInfo = Engine.DetectHandheldEnvironment();
                if (handheldInfo != null && handheldInfo.IsHandheldDetected)
                {
                    ToggleHandheldMode(true);
                    string devName = !string.IsNullOrEmpty(handheldInfo.DetectedDevice) ? handheldInfo.DetectedDevice : "Handheld";
                    ShowToast(string.Format("🎮 Handheld Mode automatically enabled ({0}: {1})", devName, handheldInfo.DetectionReason));
                }
            }
            catch { }

            StartGamepadPolling();
        }

        private void MainWindow_PreviewKeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.F11)
            {
                ToggleHandheldMode();
                e.Handled = true;
                return;
            }
            if ((Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control && (e.Key == Key.K || e.Key == Key.F))
            {
                if (_txtSearch != null)
                {
                    SwitchTab("games");
                    _txtSearch.Focus();
                    _txtSearch.SelectAll();
                    e.Handled = true;
                }
            }
            else if (e.Key == Key.Escape)
            {
                if (_drawerPanel != null && _drawerPanel.Visibility == Visibility.Visible)
                {
                    CloseDrawer();
                    e.Handled = true;
                }
                else if (_txtSearch != null && !string.IsNullOrEmpty(_txtSearch.Text))
                {
                    _txtSearch.Text = "";
                    e.Handled = true;
                }
            }
            else if (e.Key == Key.F5)
            {
                RefreshGames();
                ShowToast("Library rescanned");
                e.Handled = true;
            }
        }

        private void MainWindow_DragEnter(object sender, DragEventArgs e)
        {
            if (e.Data != null && e.Data.GetDataPresent(DataFormats.FileDrop))
            {
                e.Effects = DragDropEffects.Copy;
                if (_dropOverlay != null) _dropOverlay.Visibility = Visibility.Visible;
            }
            else
            {
                e.Effects = DragDropEffects.None;
            }
            e.Handled = true;
        }

        private void MainWindow_DragLeave(object sender, DragEventArgs e)
        {
            if (_dropOverlay != null) _dropOverlay.Visibility = Visibility.Collapsed;
        }

        private void MainWindow_Drop(object sender, DragEventArgs e)
        {
            if (_dropOverlay != null) _dropOverlay.Visibility = Visibility.Collapsed;
            if (e.Data == null || !e.Data.GetDataPresent(DataFormats.FileDrop)) return;

            string[] dropped = e.Data.GetData(DataFormats.FileDrop) as string[];
            if (dropped == null || dropped.Length == 0) return;

            int added = 0;
            string lastFolder = null;
            foreach (var rawPath in dropped)
            {
                if (string.IsNullOrEmpty(rawPath)) continue;
                string folder = rawPath;
                if (File.Exists(rawPath))
                {
                    folder = Path.GetDirectoryName(rawPath);
                }
                folder = Engine.NormalizePath(folder);
                if (!string.IsNullOrEmpty(folder) && Directory.Exists(folder))
                {
                    lastFolder = folder;
                    bool exists = false;
                    foreach (var cf in _customFolders)
                    {
                        if (string.Equals(Engine.NormalizePath(cf), folder, StringComparison.OrdinalIgnoreCase))
                        {
                            exists = true;
                            break;
                        }
                    }
                    if (!exists)
                    {
                        _customFolders.Add(folder);
                        added++;
                    }
                }
            }

            if (added > 0 || lastFolder != null)
            {
                SaveSettings();
                RefreshGames();
                SwitchTab("games");
                if (lastFolder != null)
                {
                    foreach (var g in _allGames)
                    {
                        if (string.Equals(g.Folder, lastFolder, StringComparison.OrdinalIgnoreCase) ||
                            string.Equals(g.ExeFolder, lastFolder, StringComparison.OrdinalIgnoreCase))
                        {
                            OpenDrawer(g);
                            break;
                        }
                    }
                }
                ShowToast(string.Format("Added {0} game folder(s) via Drag & Drop", Math.Max(1, added)));
            }
        }

        private void ShowToast(string message)
        {
            if (_toastBanner == null || _txtToastMessage == null) return;
            _txtToastMessage.Text = "✦  " + message;
            _toastBanner.Visibility = Visibility.Visible;
            _toastBanner.Opacity = 0;

            var fadeIn = new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(180));
            _toastBanner.BeginAnimation(UIElement.OpacityProperty, fadeIn);

            if (_toastTimer == null)
            {
                _toastTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3.2) };
                _toastTimer.Tick += delegate
                {
                    _toastTimer.Stop();
                    var fadeOut = new DoubleAnimation(1, 0, TimeSpan.FromMilliseconds(220));
                    fadeOut.Completed += delegate { if (_toastBanner != null) _toastBanner.Visibility = Visibility.Collapsed; };
                    if (_toastBanner != null) _toastBanner.BeginAnimation(UIElement.OpacityProperty, fadeOut);
                };
            }
            _toastTimer.Stop();
            _toastTimer.Start();
        }

        private void LoadSettings()
        {
            string cfg = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "config.json");
            if (File.Exists(cfg))
            {
                try
                {
                    var serializer = new System.Web.Script.Serialization.JavaScriptSerializer();
                    var data = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(cfg));
                    if (data != null)
                    {
                        if (data.ContainsKey("customFolders"))
                        {
                            _customFolders.Clear();
                            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                            var list = data["customFolders"] as System.Collections.ArrayList;
                            if (list != null)
                            {
                                foreach (var item in list)
                                {
                                    string s = Engine.NormalizePath(item.ToString());
                                    if (!string.IsNullOrEmpty(s) && seen.Add(s)) _customFolders.Add(s);
                                }
                            }
                        }
                        if (data.ContainsKey("lightTheme") && data["lightTheme"] is bool)
                        {
                            _isLightTheme = (bool)data["lightTheme"];
                        }
                    }
                }
                catch { }
            }
        }

        private void SaveSettings()
        {
            string cfg = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "config.json");
            try
            {
                var serializer = new System.Web.Script.Serialization.JavaScriptSerializer();
                var data = new Dictionary<string, object>
                {
                    { "customFolders", _customFolders },
                    { "lightTheme", _isLightTheme }
                };
                File.WriteAllText(cfg, serializer.Serialize(data));
            }
            catch { }
        }

        private void BuildUi()
        {
            var outerShell = new Grid();

            // Ambient Aurora Glow Canvas (Gold & Cyan radial background glows)
            if (!_isLightTheme)
            {
                var auroraCanvas = new Grid { IsHitTestVisible = false, ClipToBounds = true };
                var glowGold = new Ellipse
                {
                    Width = 540,
                    Height = 360,
                    HorizontalAlignment = HorizontalAlignment.Left,
                    VerticalAlignment = VerticalAlignment.Top,
                    Margin = new Thickness(-120, -140, 0, 0),
                    Fill = new RadialGradientBrush(Color.FromArgb(36, 241, 196, 15), Colors.Transparent)
                };
                var glowCyan = new Ellipse
                {
                    Width = 560,
                    Height = 400,
                    HorizontalAlignment = HorizontalAlignment.Right,
                    VerticalAlignment = VerticalAlignment.Top,
                    Margin = new Thickness(0, -150, -100, 0),
                    Fill = new RadialGradientBrush(Color.FromArgb(26, 57, 213, 255), Colors.Transparent)
                };
                var glowAmber = new Ellipse
                {
                    Width = 620,
                    Height = 420,
                    HorizontalAlignment = HorizontalAlignment.Center,
                    VerticalAlignment = VerticalAlignment.Bottom,
                    Margin = new Thickness(100, 0, 0, -200),
                    Fill = new RadialGradientBrush(Color.FromArgb(22, 243, 156, 18), Colors.Transparent)
                };
                auroraCanvas.Children.Add(glowGold);
                auroraCanvas.Children.Add(glowCyan);
                auroraCanvas.Children.Add(glowAmber);
                outerShell.Children.Add(auroraCanvas);
            }

            // Shell Grid with floating sidebar & main content
            _rootGrid = new Grid { Margin = new Thickness(14) };
            _rootGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(248) }); // Floating Sidebar
            _rootGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(14) });  // Gap
            _rootGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) }); // Main Content

            // 1. Floating Sidebar
            _rootGrid.Children.Add(BuildSidebar());

            // 2. Main Container (Floating Rounded Card Shell)
            var mainBorder = new Border
            {
                Background = new SolidColorBrush(_isLightTheme ? Color.FromArgb(220, 255, 255, 255) : Color.FromArgb(200, 14, 18, 25)),
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(22),
                ClipToBounds = true
            };
            Grid.SetColumn(mainBorder, 2);

            var mainContainer = new Grid();
            mainContainer.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // Topbar
            mainContainer.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) }); // Content

            mainContainer.Children.Add(BuildTopBar());
            mainContainer.Children.Add(BuildContentPanes());

            mainBorder.Child = mainContainer;
            _rootGrid.Children.Add(mainBorder);
            outerShell.Children.Add(_rootGrid);

            // 3. Drag & Drop Glassmorphic Overlay
            _dropOverlay = new Border
            {
                Background = new SolidColorBrush(Color.FromArgb(210, 6, 10, 16)),
                BorderBrush = AccentEmerald,
                BorderThickness = new Thickness(2),
                CornerRadius = new CornerRadius(22),
                Margin = new Thickness(18),
                Visibility = Visibility.Collapsed,
                IsHitTestVisible = false
            };
            var dropStack = new StackPanel { HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
            dropStack.Children.Add(new TextBlock { Text = "📥", FontSize = 46, HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 0, 0, 10) });
            dropStack.Children.Add(new TextBlock { Text = "Drop Game Folder or Executable Here", FontSize = 20, FontWeight = FontWeights.Bold, Foreground = Brushes.White, HorizontalAlignment = HorizontalAlignment.Center });
            dropStack.Children.Add(new TextBlock { Text = "HelixSR Manager will automatically scan the game and open its configuration drawer.", FontSize = 13, Foreground = TextMuted, HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 6, 0, 0) });
            _dropOverlay.Child = dropStack;
            outerShell.Children.Add(_dropOverlay);

            // 4. Floating Reactive Toast Notification
            _toastBanner = new Border
            {
                Background = new SolidColorBrush(Color.FromRgb(18, 25, 35)),
                BorderBrush = AccentEmerald,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(12),
                Padding = new Thickness(16, 10, 16, 10),
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Bottom,
                Margin = new Thickness(0, 0, 28, 26),
                Visibility = Visibility.Collapsed,
                IsHitTestVisible = false,
                Effect = new DropShadowEffect { Color = Colors.Black, BlurRadius = 18, ShadowDepth = 4, Opacity = 0.55 }
            };
            _txtToastMessage = new TextBlock
            {
                Text = "",
                FontSize = 12.5,
                FontWeight = FontWeights.SemiBold,
                Foreground = Brushes.White
            };
            _toastBanner.Child = _txtToastMessage;
            outerShell.Children.Add(_toastBanner);

            // 5. Handheld Controller Legend Bar
            _handheldLegendBar = BuildHandheldLegendBar();
            outerShell.Children.Add(_handheldLegendBar);

            Content = outerShell;
        }

        #region Sidebar UI
        private FrameworkElement BuildSidebar()
        {
            var sidebar = new Border
            {
                Background = BgSidebar,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(22),
                Effect = new DropShadowEffect { Color = Colors.Black, BlurRadius = 24, ShadowDepth = 6, Opacity = _isLightTheme ? 0.08 : 0.45 }
            };

            var grid = new Grid();
            grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(88) }); // Brand Header
            grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) }); // Nav Items
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // Live Engine Status Card

            // Header Brand Logo
            var logoPanel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(18, 8, 16, 0)
            };

            var logoBox = new Border
            {
                Width = 42,
                Height = 42,
                CornerRadius = new CornerRadius(12),
                Background = new LinearGradientBrush(Color.FromRgb(241, 196, 15), Color.FromRgb(243, 156, 18), 45),
                Margin = new Thickness(0, 0, 12, 0),
                Effect = new DropShadowEffect { Color = Color.FromRgb(241, 196, 15), BlurRadius = 14, ShadowDepth = 0, Opacity = 0.4 }
            };
            var logoTxt = new TextBlock
            {
                Text = "⚡",
                FontSize = 20,
                Foreground = new SolidColorBrush(Color.FromRgb(10, 12, 16)),
                FontWeight = FontWeights.Bold,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center
            };
            logoBox.Child = logoTxt;

            var titlePanel = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            var titleRow = new StackPanel { Orientation = Orientation.Horizontal };
            titleRow.Children.Add(new TextBlock
            {
                Text = "HelixSR",
                FontSize = 18,
                FontWeight = FontWeights.Bold,
                Foreground = TextMain
            });
            var verPill = new Border
            {
                Background = AccentEmeraldBg,
                BorderBrush = BorderStrong,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(5),
                Padding = new Thickness(5, 1, 5, 1),
                Margin = new Thickness(7, 2, 0, 0),
                VerticalAlignment = VerticalAlignment.Center
            };
            verPill.Child = new TextBlock { Text = "v" + Engine.AppVersion, FontSize = 9.5, FontWeight = FontWeights.Bold, Foreground = AccentEmerald };
            verPill.ToolTip = string.Format("HelixSR Manager v{0} • HelixSR Core v{1}", Engine.AppVersion, Engine.CoreVersion);
            titleRow.Children.Add(verPill);

            var subtitle = new TextBlock
            {
                Text = "HELIXSR MANAGER",
                FontSize = 9.5,
                FontWeight = FontWeights.Bold,
                Foreground = TextDim,
                Margin = new Thickness(0, 2, 0, 0)
            };
            titlePanel.Children.Add(titleRow);
            titlePanel.Children.Add(subtitle);

            logoPanel.Children.Add(logoBox);
            logoPanel.Children.Add(titlePanel);
            grid.Children.Add(logoPanel);

            // Nav List
            var navStack = new StackPanel
            {
                Margin = new Thickness(12, 8, 12, 0)
            };
            Grid.SetRow(navStack, 1);

            navStack.Children.Add(new TextBlock
            {
                Text = "WORKSPACE",
                FontSize = 10,
                FontWeight = FontWeights.Bold,
                Foreground = TextDim,
                Margin = new Thickness(12, 0, 0, 6)
            });

            _navDots.Clear();
            _txtGameCountBadge = new TextBlock
            {
                Text = "0",
                FontSize = 11,
                FontWeight = FontWeights.Bold,
                Foreground = AccentEmerald
            };
            var countPill = new Border
            {
                Background = AccentEmeraldBg,
                CornerRadius = new CornerRadius(8),
                Padding = new Thickness(7, 2, 7, 2),
                VerticalAlignment = VerticalAlignment.Center,
                Child = _txtGameCountBadge
            };

            _navBtnGames = CreateNavButton("🎮", "Games Library", "games", countPill);

            _dotCoreStatus = new Ellipse
            {
                Width = 8,
                Height = 8,
                Fill = AccentAmber,
                VerticalAlignment = VerticalAlignment.Center
            };
            _navBtnCore = CreateNavButton("⚡", "Engine & Weights", "core", _dotCoreStatus);
            _navBtnMyFsr = CreateNavButton("📦", "Custom FSR (my-fsr)", "myfsr", null);

            navStack.Children.Add(_navBtnGames);
            navStack.Children.Add(_navBtnCore);
            navStack.Children.Add(_navBtnMyFsr);

            navStack.Children.Add(new TextBlock
            {
                Text = "SYSTEM",
                FontSize = 10,
                FontWeight = FontWeights.Bold,
                Foreground = TextDim,
                Margin = new Thickness(12, 18, 0, 6)
            });

            _navBtnSettings = CreateNavButton("⚙️", "Scan & Settings", "settings", null);
            _navBtnAbout = CreateNavButton("🩺", "Hardware & About", "about", null);

            navStack.Children.Add(_navBtnSettings);
            navStack.Children.Add(_navBtnAbout);

            grid.Children.Add(navStack);

            // Bottom Live Status Card
            var statusCard = new Border
            {
                Background = BgSurface2,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(16),
                Margin = new Thickness(12, 8, 12, 12),
                Padding = new Thickness(14, 12, 14, 12),
                Cursor = Cursors.Hand
            };
            statusCard.MouseLeftButtonUp += delegate { SwitchTab("core"); };
            Grid.SetRow(statusCard, 2);

            var scStack = new StackPanel();
            var statusTopRow = new DockPanel { Margin = new Thickness(0, 0, 0, 6) };
            _dotSidebarCardStatus = new Ellipse
            {
                Width = 8,
                Height = 8,
                Fill = AccentEmerald,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 8, 0),
                Effect = new DropShadowEffect { Color = Color.FromRgb(241, 196, 15), BlurRadius = 8, ShadowDepth = 0, Opacity = 0.85 }
            };
            _txtSidebarCardStatus = new TextBlock
            {
                Text = "Engine Ready",
                FontSize = 11.5,
                FontWeight = FontWeights.Bold,
                Foreground = TextMain,
                VerticalAlignment = VerticalAlignment.Center
            };
            statusTopRow.Children.Add(_dotSidebarCardStatus);
            statusTopRow.Children.Add(_txtSidebarCardStatus);
            scStack.Children.Add(statusTopRow);

            // Progress bar track
            var track = new Border
            {
                Height = 5,
                Background = new SolidColorBrush(Color.FromArgb(35, 255, 255, 255)),
                CornerRadius = new CornerRadius(3),
                Margin = new Thickness(0, 2, 0, 8),
                ClipToBounds = true
            };
            _barSidebarProgress = new Border
            {
                Height = 5,
                HorizontalAlignment = HorizontalAlignment.Left,
                Width = 190,
                CornerRadius = new CornerRadius(3),
                Background = new LinearGradientBrush(Color.FromRgb(241, 196, 15), Color.FromRgb(243, 156, 18), 0)
            };
            track.Child = _barSidebarProgress;
            scStack.Children.Add(track);

            _txtGpuFooter = new TextBlock
            {
                Text = "Detecting GPU...",
                FontSize = 11,
                FontWeight = FontWeights.SemiBold,
                Foreground = TextMuted,
                TextTrimming = TextTrimming.CharacterEllipsis,
                Margin = new Thickness(0, 0, 0, 2)
            };
            var versionTag = new TextBlock
            {
                Text = "D3D12 Compute • Standalone",
                FontSize = 10,
                Foreground = TextDim
            };

            scStack.Children.Add(_txtGpuFooter);
            scStack.Children.Add(versionTag);
            statusCard.Child = scStack;
            grid.Children.Add(statusCard);

            sidebar.Child = grid;
            return sidebar;
        }

        private Button CreateNavButton(string icon, string label, string tabKey, UIElement rightBadge)
        {
            var dock = new DockPanel { LastChildFill = true };

            var activeDot = new Ellipse
            {
                Width = 6,
                Height = 6,
                Fill = AccentEmerald,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 10, 0),
                Visibility = Visibility.Hidden,
                Effect = new DropShadowEffect { Color = Color.FromRgb(241, 196, 15), BlurRadius = 8, ShadowDepth = 0, Opacity = 0.9 }
            };
            _navDots[tabKey] = activeDot;
            DockPanel.SetDock(activeDot, Dock.Left);
            dock.Children.Add(activeDot);

            if (rightBadge != null)
            {
                DockPanel.SetDock(rightBadge, Dock.Right);
                dock.Children.Add(rightBadge);
            }

            var leftStack = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            leftStack.Children.Add(new TextBlock { Text = icon, FontSize = 14, Width = 24, VerticalAlignment = VerticalAlignment.Center });
            leftStack.Children.Add(new TextBlock { Text = label, FontSize = 13, FontWeight = FontWeights.SemiBold, VerticalAlignment = VerticalAlignment.Center });
            dock.Children.Add(leftStack);

            var btn = new Button
            {
                Content = dock,
                Background = Brushes.Transparent,
                Foreground = TextMuted,
                BorderBrush = Brushes.Transparent,
                BorderThickness = new Thickness(1),
                Height = 42,
                Margin = new Thickness(0, 2, 0, 2),
                Padding = new Thickness(12, 0, 12, 0),
                Cursor = Cursors.Hand
            };
            if (Resources.Contains("SidebarNavButtonStyle"))
            {
                btn.Style = (Style)Resources["SidebarNavButtonStyle"];
            }

            btn.Click += delegate { SwitchTab(tabKey); };
            return btn;
        }

        private void SwitchTab(string tabKey)
        {
            _currentTab = tabKey;
            _paneGames.Visibility = tabKey == "games" ? Visibility.Visible : Visibility.Collapsed;
            _paneCore.Visibility = tabKey == "core" ? Visibility.Visible : Visibility.Collapsed;
            _paneMyFsr.Visibility = tabKey == "myfsr" ? Visibility.Visible : Visibility.Collapsed;
            _paneSettings.Visibility = tabKey == "settings" ? Visibility.Visible : Visibility.Collapsed;
            _paneAbout.Visibility = tabKey == "about" ? Visibility.Visible : Visibility.Collapsed;

            UpdateNavButtonVisual(_navBtnGames, "games", tabKey);
            UpdateNavButtonVisual(_navBtnCore, "core", tabKey);
            UpdateNavButtonVisual(_navBtnMyFsr, "myfsr", tabKey);
            UpdateNavButtonVisual(_navBtnSettings, "settings", tabKey);
            UpdateNavButtonVisual(_navBtnAbout, "about", tabKey);

            if (tabKey == "core") UpdateCoreStatus();
        }

        private void UpdateNavButtonVisual(Button btn, string key, string activeKey)
        {
            if (btn == null) return;
            bool isActive = key == activeKey;
            btn.Background = isActive ? AccentEmeraldBg : Brushes.Transparent;
            btn.BorderBrush = isActive ? BorderStrong : Brushes.Transparent;
            btn.Foreground = isActive ? TextMain : TextMuted;
            if (_navDots.ContainsKey(key))
            {
                _navDots[key].Visibility = isActive ? Visibility.Visible : Visibility.Hidden;
            }
        }
        #endregion

        #region TopBar UI
        private FrameworkElement BuildTopBar()
        {
            var bar = new Border
            {
                Background = BgSidebar,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(0, 0, 0, 1),
                Padding = new Thickness(18, 12, 18, 12)
            };

            var dock = new DockPanel { LastChildFill = true };

            // Right Action Buttons
            var rightWrap = new WrapPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center
            };
            DockPanel.SetDock(rightWrap, Dock.Right);

            var btnAddGame = CreateButton("＋ Add Game", BgCardHover, TextMain, delegate { AddCustomGameFolder(); });
            btnAddGame.Margin = new Thickness(0, 2, 6, 2);
            btnAddGame.ToolTip = "Add a custom game folder (or drag & drop a folder anywhere onto the window)";

            var btnRefresh = CreateButton("↻ Rescan", BgCardHover, TextMain, delegate { RefreshGames(); ShowToast("Game library rescanned"); });
            btnRefresh.Margin = new Thickness(0, 2, 6, 2);
            btnRefresh.ToolTip = "Rescan all Steam and Custom game libraries (F5)";

            var btnInstallAll = CreateButton("⚡ Install All", AccentEmeraldStrong, TextOnAccent, delegate { BatchInstall(true); });
            btnInstallAll.Margin = new Thickness(0, 2, 6, 2);

            var btnRestoreAll = CreateButton("↩ Restore All", BgCardHover, TextMain, delegate { BatchInstall(false); });
            btnRestoreAll.Margin = new Thickness(0, 2, 6, 2);

            var btnToggleView = CreateButton(_isGridView ? "☰ List" : "🔲 Grid", BgCardHover, TextMain, null);
            btnToggleView.Margin = new Thickness(0, 2, 6, 2);
            btnToggleView.Click += delegate
            {
                _isGridView = !_isGridView;
                btnToggleView.Content = _isGridView ? "☰ List" : "🔲 Grid";
                _gamesScrollViewer.Visibility = _isGridView ? Visibility.Visible : Visibility.Collapsed;
                _listGamesView.Visibility = _isGridView ? Visibility.Collapsed : Visibility.Visible;
            };

            var btnTheme = CreateButton(_isLightTheme ? "🌙 Dark" : "☀️ Light", BgCardHover, TextMain, delegate { ToggleTheme(); });
            btnTheme.Margin = new Thickness(0, 2, 6, 2);
            btnTheme.ToolTip = "Switch between HelixSR Manager Dark Gold and Clean Light theme";

            _btnHandheldToggle = CreateButton("🎮 Handheld", BgCardHover, TextMain, delegate { ToggleHandheldMode(); });
            _btnHandheldToggle.Margin = new Thickness(0, 2, 0, 2);
            _btnHandheldToggle.ToolTip = "Toggle Fullscreen Handheld & Controller Navigation Mode (F11 / Controller View Button)";

            rightWrap.Children.Add(btnAddGame);
            rightWrap.Children.Add(btnRefresh);
            rightWrap.Children.Add(btnInstallAll);
            rightWrap.Children.Add(btnRestoreAll);
            rightWrap.Children.Add(btnToggleView);
            rightWrap.Children.Add(btnTheme);
            rightWrap.Children.Add(_btnHandheldToggle);
            dock.Children.Add(rightWrap);

            // Left Search & Dropdown Filters
            var leftWrap = new WrapPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center
            };

            // Modern Search Box with Placeholder & Clear Button
            var searchBorder = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Width = 245,
                Height = 36,
                Margin = new Thickness(0, 2, 8, 2)
            };
            var searchGrid = new Grid();
            searchGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(32) });
            searchGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            searchGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            searchGrid.Children.Add(new TextBlock
            {
                Text = "🔍",
                FontSize = 12,
                Foreground = TextDim,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center
            });

            _txtSearchPlaceholder = new TextBlock
            {
                Text = "Search games or APIs... (Ctrl+K)",
                FontSize = 12,
                Foreground = TextDim,
                VerticalAlignment = VerticalAlignment.Center,
                IsHitTestVisible = false,
                Margin = new Thickness(2, 0, 0, 0)
            };
            Grid.SetColumn(_txtSearchPlaceholder, 1);
            searchGrid.Children.Add(_txtSearchPlaceholder);

            var btnClearSearch = new Button
            {
                Content = "✕",
                Width = 24,
                Height = 24,
                Background = Brushes.Transparent,
                Foreground = TextDim,
                BorderThickness = new Thickness(0),
                Cursor = Cursors.Hand,
                Visibility = Visibility.Collapsed,
                Margin = new Thickness(0, 0, 4, 0)
            };
            Grid.SetColumn(btnClearSearch, 2);

            _txtSearch = new TextBox
            {
                FontSize = 12.5,
                Background = Brushes.Transparent,
                Foreground = TextMain,
                CaretBrush = AccentEmerald,
                BorderThickness = new Thickness(0),
                VerticalContentAlignment = VerticalAlignment.Center,
                Padding = new Thickness(0, 0, 4, 0)
            };
            Grid.SetColumn(_txtSearch, 1);

            btnClearSearch.Click += delegate { _txtSearch.Text = ""; _txtSearch.Focus(); };
            _txtSearch.TextChanged += delegate
            {
                bool hasText = !string.IsNullOrEmpty(_txtSearch.Text);
                _txtSearchPlaceholder.Visibility = hasText ? Visibility.Collapsed : Visibility.Visible;
                btnClearSearch.Visibility = hasText ? Visibility.Visible : Visibility.Collapsed;
                FilterGames();
            };

            searchGrid.Children.Add(_txtSearch);
            searchGrid.Children.Add(btnClearSearch);
            searchBorder.Child = searchGrid;

            // Dropdown Filters (Using Custom Dark/Light ComboBox Template)
            _cmbLauncher = new ComboBox
            {
                Width = 122,
                Height = 36,
                Margin = new Thickness(0, 2, 8, 2),
                FontSize = 12
            };
            _cmbLauncher.Items.Add("All Launchers");
            _cmbLauncher.Items.Add("Steam");
            _cmbLauncher.Items.Add("Custom");
            _cmbLauncher.SelectedIndex = 0;
            _cmbLauncher.SelectionChanged += delegate { FilterGames(); };

            _cmbStatus = new ComboBox
            {
                Width = 128,
                Height = 36,
                Margin = new Thickness(0, 2, 8, 2),
                FontSize = 12
            };
            _cmbStatus.Items.Add("All Status");
            _cmbStatus.Items.Add("HelixSR Active");
            _cmbStatus.Items.Add("Not Installed");
            _cmbStatus.SelectedIndex = 0;
            _cmbStatus.SelectionChanged += delegate { FilterGames(); };

            _cmbSort = new ComboBox
            {
                Width = 126,
                Height = 36,
                Margin = new Thickness(0, 2, 8, 2),
                FontSize = 12
            };
            _cmbSort.Items.Add("Name (A-Z)");
            _cmbSort.Items.Add("Name (Z-A)");
            _cmbSort.Items.Add("Installed First");
            _cmbSort.SelectedIndex = 0;
            _cmbSort.SelectionChanged += delegate { FilterGames(); };

            leftWrap.Children.Add(searchBorder);
            leftWrap.Children.Add(_cmbLauncher);
            leftWrap.Children.Add(_cmbStatus);
            leftWrap.Children.Add(_cmbSort);

            dock.Children.Add(leftWrap);
            bar.Child = dock;
            return bar;
        }

        private Button CreateButton(string text, Brush bg, Brush fg, RoutedEventHandler onClick)
        {
            var btn = new Button
            {
                Content = text,
                Background = bg,
                Foreground = fg ?? Brushes.White,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                Height = 35,
                Padding = new Thickness(13, 0, 13, 0),
                FontSize = 12,
                FontWeight = FontWeights.SemiBold,
                Cursor = Cursors.Hand
            };
            if (Resources.Contains("PillButtonStyle"))
            {
                btn.Style = (Style)Resources["PillButtonStyle"];
            }
            if (onClick != null) btn.Click += onClick;
            return btn;
        }
        #endregion

        #region Content Panes
        private FrameworkElement BuildContentPanes()
        {
            var root = new Grid();
            Grid.SetRow(root, 1);

            _paneGames = BuildGamesPane();
            _paneCore = BuildCorePane();
            _paneMyFsr = BuildMyFsrPane();
            _paneSettings = BuildSettingsPane();
            _paneAbout = BuildAboutPane();

            root.Children.Add(_paneGames);
            root.Children.Add(_paneCore);
            root.Children.Add(_paneMyFsr);
            root.Children.Add(_paneSettings);
            root.Children.Add(_paneAbout);

            SwitchTab("games");
            return root;
        }

        private Grid BuildGamesPane()
        {
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto }); // Drawer

            // Main Games Area
            var leftArea = new Grid();
            leftArea.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // Hero Banner + Stat Cards
            leftArea.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); // Interactive Filter Pills
            leftArea.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) }); // Grid/List

            // 1. Hero Header + Live Stat Counters
            var heroBanner = new Border
            {
                Background = new LinearGradientBrush(
                    _isLightTheme ? Color.FromArgb(35, 241, 196, 15) : Color.FromArgb(32, 241, 196, 15),
                    _isLightTheme ? Color.FromArgb(20, 243, 156, 18) : Color.FromArgb(18, 57, 213, 255),
                    15),
                BorderBrush = BorderStrong,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(16),
                Margin = new Thickness(20, 16, 20, 10),
                Padding = new Thickness(18, 14, 18, 14)
            };

            var heroDock = new DockPanel();

            // Right Live Stat Counter Chips
            var statRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            DockPanel.SetDock(statRow, Dock.Right);

            statRow.Children.Add(BuildStatChip("TOTAL GAMES", out _txtStatTotal, TextMain));
            statRow.Children.Add(BuildStatChip("HELIXSR ACTIVE", out _txtStatActive, AccentEmerald));
            statRow.Children.Add(BuildStatChip("DIRECT FSR 3.1", out _txtStatDirect, AccentSky));
            statRow.Children.Add(BuildStatChip("OPTISCALER", out _txtStatOpti, AccentViolet));
            heroDock.Children.Add(statRow);

            var bannerStack = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            var titleBadgeRow = new StackPanel { Orientation = Orientation.Horizontal };
            titleBadgeRow.Children.Add(new TextBlock
            {
                Text = "Neural Super Resolution Library",
                FontSize = 16.5,
                FontWeight = FontWeights.Bold,
                Foreground = TextMain
            });
            var dropHintBadge = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(6),
                Padding = new Thickness(8, 2, 8, 2),
                Margin = new Thickness(10, 0, 0, 0),
                VerticalAlignment = VerticalAlignment.Center
            };
            dropHintBadge.Child = new TextBlock { Text = "📥 Drag & Drop Folders Supported", FontSize = 10, FontWeight = FontWeights.SemiBold, Foreground = TextMuted };
            titleBadgeRow.Children.Add(dropHintBadge);

            bannerStack.Children.Add(titleBadgeRow);
            bannerStack.Children.Add(new TextBlock
            {
                Text = "Swap native FSR 3.1 DLLs or inject OptiScaler hooks with DLSS Model E compute shaders & automatic REFramework nightly support.",
                FontSize = 12,
                Foreground = TextMuted,
                Margin = new Thickness(0, 4, 0, 0),
                TextTrimming = TextTrimming.CharacterEllipsis
            });
            heroDock.Children.Add(bannerStack);
            heroBanner.Child = heroDock;
            leftArea.Children.Add(heroBanner);

            // 2. Interactive Quick-Filter Pill Bar
            var filterPillBar = new WrapPanel
            {
                Orientation = Orientation.Horizontal,
                Margin = new Thickness(20, 0, 20, 10)
            };
            Grid.SetRow(filterPillBar, 1);

            _filterPillButtons.Clear();
            filterPillBar.Children.Add(CreateFilterPillButton("all", "All Games"));
            filterPillBar.Children.Add(CreateFilterPillButton("installed", "⚡ HelixSR Active"));
            filterPillBar.Children.Add(CreateFilterPillButton("uninstalled", "○ Not Installed"));
            filterPillBar.Children.Add(CreateFilterPillButton("direct", "🎯 Direct FSR 3.1"));
            filterPillBar.Children.Add(CreateFilterPillButton("optiscaler", "🔌 OptiScaler Hook"));
            filterPillBar.Children.Add(CreateFilterPillButton("reengine", "🧬 Capcom RE Engine"));
            UpdateFilterPillVisuals();
            leftArea.Children.Add(filterPillBar);

            // 3. Empty State / Dropzone Card
            _emptyStatePanel = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(16),
                Padding = new Thickness(36),
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Visibility = Visibility.Collapsed
            };
            var emptyStack = new StackPanel { HorizontalAlignment = HorizontalAlignment.Center };
            emptyStack.Children.Add(new TextBlock { Text = "🎮", FontSize = 36, HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 0, 0, 8) });
            emptyStack.Children.Add(new TextBlock { Text = "No matching games in current view", FontSize = 15, FontWeight = FontWeights.Bold, Foreground = TextMain, HorizontalAlignment = HorizontalAlignment.Center });
            emptyStack.Children.Add(new TextBlock { Text = "Clear your active filters, click '＋ Add Game', or drag & drop any game folder here.", FontSize = 12, Foreground = TextMuted, HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 4, 0, 14) });
            var btnResetFilters = CreateButton("Reset Filters", AccentEmeraldStrong, TextOnAccent, delegate
            {
                _quickFilter = "all";
                if (_txtSearch != null) _txtSearch.Text = "";
                if (_cmbLauncher != null) _cmbLauncher.SelectedIndex = 0;
                if (_cmbStatus != null) _cmbStatus.SelectedIndex = 0;
                UpdateFilterPillVisuals();
                FilterGames();
            });
            btnResetFilters.HorizontalAlignment = HorizontalAlignment.Center;
            emptyStack.Children.Add(btnResetFilters);
            _emptyStatePanel.Child = emptyStack;
            Grid.SetRow(_emptyStatePanel, 2);
            leftArea.Children.Add(_emptyStatePanel);

            // 4. Grid View (WrapPanel)
            _gridWrapPanel = new WrapPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(14, 0, 14, 18) };
            _gamesScrollViewer = new ScrollViewer
            {
                Content = _gridWrapPanel,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
            };
            Grid.SetRow(_gamesScrollViewer, 2);
            leftArea.Children.Add(_gamesScrollViewer);

            // 5. List View
            _listGamesView = new ListView
            {
                Background = BgCard,
                Foreground = TextMain,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                Margin = new Thickness(20, 0, 20, 16),
                Visibility = Visibility.Collapsed
            };
            var gv = new GridView();
            gv.Columns.Add(new GridViewColumn { Header = "Game Title", DisplayMemberBinding = new System.Windows.Data.Binding("Name"), Width = 270 });
            gv.Columns.Add(new GridViewColumn { Header = "Launcher", DisplayMemberBinding = new System.Windows.Data.Binding("Launcher"), Width = 85 });
            gv.Columns.Add(new GridViewColumn { Header = "Method", DisplayMemberBinding = new System.Windows.Data.Binding("RouteDisplay"), Width = 155 });
            gv.Columns.Add(new GridViewColumn { Header = "HelixSR Status", DisplayMemberBinding = new System.Windows.Data.Binding("StatusDisplay"), Width = 120 });
            gv.Columns.Add(new GridViewColumn { Header = "Directory", DisplayMemberBinding = new System.Windows.Data.Binding("Folder"), Width = 320 });
            _listGamesView.View = gv;
            _listGamesView.SelectionChanged += delegate
            {
                if (_listGamesView.SelectedItem is GameInfo)
                {
                    OpenDrawer((GameInfo)_listGamesView.SelectedItem);
                }
            };
            Grid.SetRow(_listGamesView, 2);
            leftArea.Children.Add(_listGamesView);

            grid.Children.Add(leftArea);

            // Right-hand Slide-Over Drawer
            _drawerPanel = BuildDrawer();
            Grid.SetColumn(_drawerPanel, 1);
            grid.Children.Add(_drawerPanel);

            return grid;
        }

        private Border BuildStatChip(string label, out TextBlock valueBlock, Brush valueBrush)
        {
            var chip = new Border
            {
                Background = BgSidebar,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(12, 6, 12, 6),
                Margin = new Thickness(8, 0, 0, 0)
            };
            var stack = new StackPanel { HorizontalAlignment = HorizontalAlignment.Center };
            valueBlock = new TextBlock
            {
                Text = "0",
                FontSize = 15,
                FontWeight = FontWeights.Bold,
                Foreground = valueBrush,
                HorizontalAlignment = HorizontalAlignment.Center
            };
            stack.Children.Add(valueBlock);
            stack.Children.Add(new TextBlock
            {
                Text = label,
                FontSize = 9,
                FontWeight = FontWeights.Bold,
                Foreground = TextDim,
                HorizontalAlignment = HorizontalAlignment.Center
            });
            chip.Child = stack;
            return chip;
        }

        private Button CreateFilterPillButton(string filterKey, string label)
        {
            var btn = new Button
            {
                Content = label,
                Tag = label,
                Height = 30,
                Padding = new Thickness(12, 0, 12, 0),
                Margin = new Thickness(0, 0, 8, 6),
                FontSize = 11.5,
                FontWeight = FontWeights.SemiBold,
                Cursor = Cursors.Hand
            };
            if (Resources.Contains("PillButtonStyle"))
            {
                btn.Style = (Style)Resources["PillButtonStyle"];
            }
            btn.Click += delegate
            {
                _quickFilter = filterKey;
                UpdateFilterPillVisuals();
                FilterGames();
            };
            _filterPillButtons[filterKey] = btn;
            return btn;
        }

        private void UpdateFilterPillVisuals()
        {
            foreach (var kv in _filterPillButtons)
            {
                bool active = kv.Key == _quickFilter;
                kv.Value.Background = active ? AccentEmeraldBg : BgCard;
                kv.Value.BorderBrush = active ? BorderStrong : BorderColor;
                kv.Value.BorderThickness = new Thickness(1);
                kv.Value.Foreground = active ? AccentEmerald : TextMuted;
            }
        }

        private Grid BuildDrawer()
        {
            var drawer = new Grid
            {
                Width = 450,
                Background = BgSidebar,
                Visibility = Visibility.Collapsed,
                RenderTransform = new TranslateTransform(0, 0)
            };

            var borderLeft = new Border
            {
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1, 0, 0, 0)
            };

            var dock = new DockPanel();

            // Top Hero Image / Banner
            _bannerDrawerHero = new Border
            {
                Height = 172,
                Background = BgCard,
                ClipToBounds = true
            };
            DockPanel.SetDock(_bannerDrawerHero, Dock.Top);
            var heroGrid = new Grid();

            _imgDrawerHero = new Image
            {
                Stretch = Stretch.UniformToFill,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center
            };
            heroGrid.Children.Add(_imgDrawerHero);

            var heroTint = new Border
            {
                Background = new LinearGradientBrush(
                    Color.FromArgb(70, 6, 8, 13),
                    _isLightTheme ? Color.FromArgb(245, 255, 255, 255) : Color.FromArgb(248, 17, 22, 30),
                    90
                )
            };
            heroGrid.Children.Add(heroTint);

            var closeBtn = new Button
            {
                Content = "✕",
                Width = 32,
                Height = 32,
                Foreground = Brushes.White,
                Background = new SolidColorBrush(Color.FromArgb(170, 10, 14, 20)),
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 12, 12, 0),
                Cursor = Cursors.Hand,
                ToolTip = "Close Drawer (Esc)"
            };
            if (Resources.Contains("PillButtonStyle")) closeBtn.Style = (Style)Resources["PillButtonStyle"];
            closeBtn.Click += delegate { CloseDrawer(); };

            var heroOverlay = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Bottom,
                Margin = new Thickness(18, 0, 18, 14),
                Orientation = Orientation.Horizontal
            };

            var thumbBorder = new Border
            {
                Width = 60,
                Height = 88,
                CornerRadius = new CornerRadius(8),
                ClipToBounds = true,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                Margin = new Thickness(0, 0, 14, 0),
                Effect = new DropShadowEffect { Color = Colors.Black, BlurRadius = 12, ShadowDepth = 3, Opacity = 0.5 }
            };
            _imgDrawerThumb = new Image
            {
                Stretch = Stretch.UniformToFill
            };
            thumbBorder.Child = _imgDrawerThumb;

            var metaStack = new StackPanel { VerticalAlignment = VerticalAlignment.Bottom };
            _txtDrawerTitle = new TextBlock
            {
                Text = "Game Title",
                FontSize = 17,
                FontWeight = FontWeights.Bold,
                Foreground = TextMain,
                TextTrimming = TextTrimming.CharacterEllipsis,
                MaxWidth = 330
            };

            var badgeStack = new WrapPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 7, 0, 0) };

            var pillPlat = new Border { Background = BgCard, BorderBrush = BorderColor, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(6), Padding = new Thickness(7, 2, 7, 2), Margin = new Thickness(0, 0, 6, 4) };
            _txtDrawerPlatform = new TextBlock { Text = "Steam", FontSize = 10.5, FontWeight = FontWeights.SemiBold, Foreground = AccentBlue };
            pillPlat.Child = _txtDrawerPlatform;

            var pillRoute = new Border { Background = BgCard, BorderBrush = BorderColor, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(6), Padding = new Thickness(7, 2, 7, 2), Margin = new Thickness(0, 0, 6, 4) };
            _txtDrawerRoute = new TextBlock { Text = "OptiScaler", FontSize = 10.5, FontWeight = FontWeights.SemiBold, Foreground = AccentSky };
            pillRoute.Child = _txtDrawerRoute;

            var pillStatus = new Border { Background = AccentEmeraldBg, BorderBrush = BorderStrong, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(6), Padding = new Thickness(7, 2, 7, 2), Margin = new Thickness(0, 0, 0, 4) };
            _txtDrawerStatus = new TextBlock { Text = "Installed", FontSize = 10.5, FontWeight = FontWeights.Bold, Foreground = AccentEmerald };
            pillStatus.Child = _txtDrawerStatus;

            badgeStack.Children.Add(pillPlat);
            badgeStack.Children.Add(pillRoute);
            badgeStack.Children.Add(pillStatus);

            metaStack.Children.Add(_txtDrawerTitle);
            metaStack.Children.Add(badgeStack);

            heroOverlay.Children.Add(thumbBorder);
            heroOverlay.Children.Add(metaStack);

            heroGrid.Children.Add(closeBtn);
            heroGrid.Children.Add(heroOverlay);
            _bannerDrawerHero.Child = heroGrid;
            dock.Children.Add(_bannerDrawerHero);

            // Scrollable Content
            var scroll = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
            var contentStack = new StackPanel { Margin = new Thickness(18, 14, 18, 18) };

            // Installation Method Selection Box
            var methodBox = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(12),
                Padding = new Thickness(14),
                Margin = new Thickness(0, 0, 0, 14)
            };
            var mStack = new StackPanel();
            var mHeader = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
            mHeader.Children.Add(new TextBlock
            {
                Text = "INSTALLATION METHOD & HOOKS",
                FontSize = 10.5,
                FontWeight = FontWeights.Bold,
                Foreground = AccentEmerald
            });
            mStack.Children.Add(mHeader);

            _cmbDrawerInstallMethod = new ComboBox
            {
                Height = 35,
                FontSize = 12,
                Margin = new Thickness(0, 0, 0, 8)
            };
            _cmbDrawerInstallMethod.SelectionChanged += delegate { OnDrawerMethodSelectionChanged(); };
            mStack.Children.Add(_cmbDrawerInstallMethod);

            _txtDrawerMethodHint = new TextBlock
            {
                Text = "",
                FontSize = 11.5,
                Foreground = TextMuted,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 10)
            };
            mStack.Children.Add(_txtDrawerMethodHint);

            _panelDrawerFg = new StackPanel { Margin = new Thickness(0, 0, 0, 8) };
            _panelDrawerFg.Children.Add(new TextBlock
            {
                Text = "FRAME GENERATION (DLSS-G HOOK / OPTIFG)",
                FontSize = 10,
                FontWeight = FontWeights.Bold,
                Foreground = AccentEmerald,
                Margin = new Thickness(0, 0, 0, 5)
            });
            _cmbDrawerFgMode = new ComboBox
            {
                Height = 33,
                FontSize = 11.5
            };
            _cmbDrawerFgMode.SelectionChanged += delegate { OnDrawerFgSelectionChanged(); };
            _panelDrawerFg.Children.Add(_cmbDrawerFgMode);
            mStack.Children.Add(_panelDrawerFg);

            _chkDrawerFakeNvapi = new System.Windows.Controls.CheckBox
            {
                Content = "Deploy FakeNVAPI (fakenvapi.dll) to unlock DLSS & DLSS-G on AMD/Intel GPUs",
                Foreground = TextMain,
                FontSize = 11.5,
                IsChecked = true,
                Cursor = Cursors.Hand,
                Margin = new Thickness(0, 0, 0, 6)
            };
            _chkDrawerFakeNvapi.Checked += delegate { if (!_updatingDrawerControls && _selectedGame != null) _selectedGame.UseFakeNvapi = true; };
            _chkDrawerFakeNvapi.Unchecked += delegate { if (!_updatingDrawerControls && _selectedGame != null) _selectedGame.UseFakeNvapi = false; };
            mStack.Children.Add(_chkDrawerFakeNvapi);

            _chkDrawerReFramework = new System.Windows.Controls.CheckBox
            {
                Content = "Install REFramework Nightly (dinput8.dll) for Capcom RE Engine",
                Foreground = TextMain,
                FontSize = 11.5,
                Cursor = Cursors.Hand,
                IsChecked = false
            };
            _chkDrawerReFramework.Checked += delegate { if (!_updatingDrawerControls && _selectedGame != null) { _selectedGame.InstallReFramework = true; UpdateDrawerMethodSummary(); } };
            _chkDrawerReFramework.Unchecked += delegate { if (!_updatingDrawerControls && _selectedGame != null) { _selectedGame.InstallReFramework = false; UpdateDrawerMethodSummary(); } };
            mStack.Children.Add(_chkDrawerReFramework);

            methodBox.Child = mStack;
            contentStack.Children.Add(methodBox);

            // Primary Actions Bar
            var actionsBar = new UniformGrid { Columns = 3, Margin = new Thickness(0, 0, 0, 12) };
            _btnDrawerInstall = CreateButton("⚡ Install HelixSR", AccentEmeraldStrong, TextOnAccent, delegate { OnInstallClicked(); });
            _btnDrawerInstall.Margin = new Thickness(0, 0, 5, 0);
            _btnDrawerUninstall = CreateButton("↩ Restore", AccentRed, Brushes.White, delegate { OnUninstallClicked(); });
            _btnDrawerUninstall.Margin = new Thickness(3, 0, 3, 0);
            var btnLaunch = CreateButton("▶ Launch Game", BgCardHover, TextMain, delegate { OnLaunchClicked(); });
            btnLaunch.Margin = new Thickness(5, 0, 0, 0);

            actionsBar.Children.Add(_btnDrawerInstall);
            actionsBar.Children.Add(_btnDrawerUninstall);
            actionsBar.Children.Add(btnLaunch);
            contentStack.Children.Add(actionsBar);

            // Folder Shortcuts & Maintenance
            var shortcuts = new UniformGrid { Columns = 4, Margin = new Thickness(0, 0, 0, 14) };
            var btnFolder = CreateButton("📁 Folder", BgCard, TextMain, delegate { if (_selectedGame != null) OpenFolderInExplorer(_selectedGame.ExeFolder ?? _selectedGame.Folder); });
            btnFolder.Margin = new Thickness(0, 0, 4, 0);
            var btnBackup = CreateButton("📂 Backups", BgCard, TextMain, delegate { if (_selectedGame != null) OpenFolderInExplorer(Path.Combine(_selectedGame.ExeFolder ?? _selectedGame.Folder, "HelixSR", "backup")); });
            btnBackup.Margin = new Thickness(2, 0, 2, 0);
            var btnMyFsr = CreateButton("📦 my-fsr", BgCard, TextMain, delegate { if (_selectedGame != null) OpenFolderInExplorer(Path.Combine(_selectedGame.ExeFolder ?? _selectedGame.Folder, "HelixSR", "my-fsr")); });
            btnMyFsr.Margin = new Thickness(2, 0, 2, 0);
            var btnPurgeCache = CreateButton("🧹 Cache", BgCard, TextMain, delegate { OnClearShaderCacheClicked(); });
            btnPurgeCache.Margin = new Thickness(4, 0, 0, 0);
            btnPurgeCache.ToolTip = "Purges Capcom RE Engine (shader.cache2) and DirectX 12 corrupted pipeline state objects.";
            shortcuts.Children.Add(btnFolder);
            shortcuts.Children.Add(btnBackup);
            shortcuts.Children.Add(btnMyFsr);
            shortcuts.Children.Add(btnPurgeCache);
            contentStack.Children.Add(shortcuts);

            // Target Game Telemetry Card
            var propBox = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(12),
                Padding = new Thickness(14, 10, 14, 10),
                Margin = new Thickness(0, 0, 0, 14)
            };
            var pStack = new StackPanel();
            _txtDrawerExe = AddPropRow(pStack, "Executable:", "-");
            _txtDrawerFolder = AddPropRow(pStack, "Location:", "-");
            _txtDrawerInputs = AddPropRow(pStack, "Detected APIs:", "-");
            _txtDrawerMethod = AddPropRow(pStack, "Active Route:", "-");
            propBox.Child = pStack;
            contentStack.Children.Add(propBox);

            // Segmented Pill Tab Bar (Replacing legacy system TabControl)
            var segBar = new Border
            {
                Background = BgSurface2,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(4),
                Margin = new Thickness(0, 0, 0, 10)
            };
            var segGrid = new UniformGrid { Columns = 3 };
            _btnDrawerTabGuide = CreateButton("📘 Setup Guide", AccentEmeraldBg, AccentEmerald, delegate { SwitchDrawerTab("guide"); });
            _btnDrawerTabGuide.Height = 30;
            _btnDrawerTabIni = CreateButton("⚙️ OptiScaler.ini", Brushes.Transparent, TextMuted, delegate { SwitchDrawerTab("ini"); });
            _btnDrawerTabIni.Height = 30;
            _btnDrawerTabLogs = CreateButton("📋 Logs", Brushes.Transparent, TextMuted, delegate { SwitchDrawerTab("logs"); });
            _btnDrawerTabLogs.Height = 30;

            segGrid.Children.Add(_btnDrawerTabGuide);
            segGrid.Children.Add(_btnDrawerTabIni);
            segGrid.Children.Add(_btnDrawerTabLogs);
            segBar.Child = segGrid;
            contentStack.Children.Add(segBar);

            // Tab 1: Setup Guide
            _drawerTabGuidePane = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(12),
                Padding = new Thickness(14)
            };
            _txtDrawerGuide = new TextBlock
            {
                Text = "",
                FontSize = 12,
                Foreground = TextMuted,
                TextWrapping = TextWrapping.Wrap,
                LineHeight = 20
            };
            _drawerTabGuidePane.Child = _txtDrawerGuide;
            contentStack.Children.Add(_drawerTabGuidePane);

            // Tab 2: OptiScaler.ini Editor
            _drawerTabIniPane = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(12),
                Padding = new Thickness(12),
                Visibility = Visibility.Collapsed
            };
            var iniStack = new StackPanel();
            var iniTop = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
            var btnSaveIni = CreateButton("💾 Save INI Changes", AccentEmeraldStrong, TextOnAccent, delegate { OnSaveIniClicked(); });
            btnSaveIni.Height = 30;
            DockPanel.SetDock(btnSaveIni, Dock.Right);
            iniTop.Children.Add(btnSaveIni);
            iniTop.Children.Add(new TextBlock { Text = "OptiScaler Configuration", FontSize = 12, FontWeight = FontWeights.Bold, Foreground = TextMain, VerticalAlignment = VerticalAlignment.Center });
            iniStack.Children.Add(iniTop);

            _txtIniEditor = new TextBox
            {
                Height = 165,
                Background = new SolidColorBrush(Color.FromRgb(10, 13, 18)),
                Foreground = new SolidColorBrush(Color.FromRgb(241, 196, 15)),
                CaretBrush = Brushes.White,
                BorderBrush = BorderColor,
                FontFamily = new FontFamily("Consolas, Courier New"),
                FontSize = 11.5,
                Padding = new Thickness(8),
                AcceptsReturn = true,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto
            };
            iniStack.Children.Add(_txtIniEditor);
            _drawerTabIniPane.Child = iniStack;
            contentStack.Children.Add(_drawerTabIniPane);

            // Tab 3: Logs & Diagnostics
            _drawerTabLogsPane = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(12),
                Padding = new Thickness(12),
                Visibility = Visibility.Collapsed
            };
            var logStack = new StackPanel();
            var logTop = new DockPanel { Margin = new Thickness(0, 0, 0, 8) };
            var logBtnRow = new StackPanel { Orientation = Orientation.Horizontal };
            DockPanel.SetDock(logBtnRow, Dock.Right);

            var btnCopyLogs = CreateButton("📋 Copy", BgCardHover, TextMain, delegate
            {
                try
                {
                    if (!string.IsNullOrEmpty(_txtLogOutput.Text))
                    {
                        Clipboard.SetText(_txtLogOutput.Text);
                        ShowToast("Diagnostic logs copied to clipboard");
                    }
                }
                catch { }
            });
            btnCopyLogs.Height = 28;
            btnCopyLogs.Margin = new Thickness(0, 0, 6, 0);

            var btnRefreshLogs = CreateButton("↻ Refresh", BgCardHover, TextMain, delegate { RefreshLogs(); ShowToast("Logs refreshed"); });
            btnRefreshLogs.Height = 28;

            logBtnRow.Children.Add(btnCopyLogs);
            logBtnRow.Children.Add(btnRefreshLogs);
            logTop.Children.Add(logBtnRow);
            logTop.Children.Add(new TextBlock { Text = "Runtime Telemetry", FontSize = 12, FontWeight = FontWeights.Bold, Foreground = TextMain, VerticalAlignment = VerticalAlignment.Center });
            logStack.Children.Add(logTop);

            _txtLogOutput = new TextBox
            {
                Height = 165,
                Background = new SolidColorBrush(Color.FromRgb(10, 13, 18)),
                Foreground = new SolidColorBrush(Color.FromRgb(203, 213, 225)),
                BorderBrush = BorderColor,
                FontFamily = new FontFamily("Consolas, Courier New"),
                FontSize = 11,
                Padding = new Thickness(8),
                IsReadOnly = true,
                AcceptsReturn = true,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto
            };
            logStack.Children.Add(_txtLogOutput);
            _drawerTabLogsPane.Child = logStack;
            contentStack.Children.Add(_drawerTabLogsPane);

            SwitchDrawerTab(_currentDrawerTab);

            scroll.Content = contentStack;
            dock.Children.Add(scroll);

            drawer.Children.Add(borderLeft);
            drawer.Children.Add(dock);
            return drawer;
        }

        private void SwitchDrawerTab(string tab)
        {
            _currentDrawerTab = tab;
            if (_drawerTabGuidePane == null) return;
            _drawerTabGuidePane.Visibility = tab == "guide" ? Visibility.Visible : Visibility.Collapsed;
            _drawerTabIniPane.Visibility = tab == "ini" ? Visibility.Visible : Visibility.Collapsed;
            _drawerTabLogsPane.Visibility = tab == "logs" ? Visibility.Visible : Visibility.Collapsed;

            StyleSegTabButton(_btnDrawerTabGuide, tab == "guide");
            StyleSegTabButton(_btnDrawerTabIni, tab == "ini");
            StyleSegTabButton(_btnDrawerTabLogs, tab == "logs");
        }

        private void StyleSegTabButton(Button btn, bool active)
        {
            if (btn == null) return;
            btn.Background = active ? AccentEmeraldBg : Brushes.Transparent;
            btn.BorderBrush = active ? BorderStrong : Brushes.Transparent;
            btn.Foreground = active ? AccentEmerald : TextMuted;
        }

        private TextBlock AddPropRow(StackPanel parent, string label, string defVal)
        {
            var p = new DockPanel { Margin = new Thickness(0, 3, 0, 3) };
            var lbl = new TextBlock { Text = label, Width = 105, FontSize = 11.5, FontWeight = FontWeights.SemiBold, Foreground = TextDim };
            var val = new TextBlock { Text = defVal, FontSize = 11.5, Foreground = TextMain, TextTrimming = TextTrimming.CharacterEllipsis };
            p.Children.Add(lbl);
            p.Children.Add(val);
            parent.Children.Add(p);
            return val;
        }

        private void PopulateDrawerMethodOptions(GameInfo game)
        {
            _updatingDrawerControls = true;
            try
            {
                _cmbDrawerInstallMethod.Items.Clear();

                bool hasNativeFsr = game.FsrTargets != null && game.FsrTargets.Count > 0;
                string directLabel = hasNativeFsr
                    ? "Direct FSR 3.1 Replacement (Native FSR 3.1 DLLs)"
                    : "Direct FSR 3.1 Replacement (Standalone FidelityFX DLLs)";

                string[][] optiOptions = new string[][]
                {
                    new string[] { "dxgi.dll", "OptiScaler Proxy — dxgi.dll (Recommended DLSS/XeSS/FSR2 Hook)" },
                    new string[] { "winmm.dll", "OptiScaler Proxy — winmm.dll (Compatibility Hook)" },
                    new string[] { "version.dll", "OptiScaler Proxy — version.dll (Alternative Hook)" },
                    new string[] { "dbghelp.dll", "OptiScaler Proxy — dbghelp.dll (Alternative Hook)" },
                    new string[] { "d3d12.dll", "OptiScaler Proxy — d3d12.dll (Direct3D 12 Hook)" },
                    new string[] { "wininet.dll", "OptiScaler Proxy — wininet.dll (Alternative Hook)" },
                    new string[] { "winhttp.dll", "OptiScaler Proxy — winhttp.dll (Alternative Hook)" },
                    new string[] { "OptiScaler.asi", "OptiScaler ASI Plugin — OptiScaler.asi (ASI Loader)" }
                };

                // OptiScaler dxgi.dll is the default option
                _cmbDrawerInstallMethod.Items.Add(new ComboBoxItem
                {
                    Content = optiOptions[0][1],
                    Tag = "optiscaler:" + optiOptions[0][0]
                });

                var itemDirect = new ComboBoxItem { Content = directLabel, Tag = "direct" };
                _cmbDrawerInstallMethod.Items.Add(itemDirect);

                for (int i = 1; i < optiOptions.Length; i++)
                {
                    _cmbDrawerInstallMethod.Items.Add(new ComboBoxItem
                    {
                        Content = optiOptions[i][1],
                        Tag = "optiscaler:" + optiOptions[i][0]
                    });
                }

                // HelixSR 1.8.1: experimental DLSS loader (games with DLSS only, never the default)
                bool hasDlss = game.Inputs != null && game.Inputs.Contains("DLSS");
                if ((hasDlss && Engine.IsDlssLoaderAvailable()) || game.Route == "dlss")
                {
                    _cmbDrawerInstallMethod.Items.Add(new ComboBoxItem
                    {
                        Content = "⚠ EXPERIMENTAL — DLSS Loader (HelixSR as the game's own DLSS, no OptiScaler)",
                        Tag = "dlss"
                    });
                }

                string targetTag = game.Route == "direct" || game.Route == "dlss"
                    ? game.Route
                    : "optiscaler:" + (string.IsNullOrEmpty(game.OptiDllName) ? "dxgi.dll" : game.OptiDllName);

                int selectedIdx = 0;
                for (int i = 0; i < _cmbDrawerInstallMethod.Items.Count; i++)
                {
                    var cbi = _cmbDrawerInstallMethod.Items[i] as ComboBoxItem;
                    if (cbi != null && string.Equals(cbi.Tag as string, targetTag, StringComparison.OrdinalIgnoreCase))
                    {
                        selectedIdx = i;
                        break;
                    }
                }
                _cmbDrawerInstallMethod.SelectedIndex = selectedIdx;

                _cmbDrawerFgMode.Items.Clear();
                string[][] fgOptions = new string[][]
                {
                    new string[] { "auto", "Frame Gen: Game Default / Pass-Through" },
                    new string[] { "dlssg_xefg", "DLSS-G Hook → Intel XeFG (AI Neural Frame Gen on AMD)" },
                    new string[] { "dlssg_fsrfg", "DLSS-G Hook → AMD FidelityFX FG (FSR 3.1 / 4.0 FG)" },
                    new string[] { "dlssg_nukems", "DLSS-G Hook → Nukem's dlssg-to-fsr3 (Streamline Swapchain)" },
                    new string[] { "optifg_fsrfg", "Universal OptiFG (Upscaler Hook + HUDFix → FSR-FG)" }
                };
                foreach (var fgOpt in fgOptions)
                {
                    _cmbDrawerFgMode.Items.Add(new ComboBoxItem { Content = fgOpt[1], Tag = fgOpt[0] });
                }

                string targetFg = string.IsNullOrEmpty(game.FgMode) ? "auto" : game.FgMode;
                int fgIdx = 0;
                for (int i = 0; i < _cmbDrawerFgMode.Items.Count; i++)
                {
                    var fcbi = _cmbDrawerFgMode.Items[i] as ComboBoxItem;
                    if (fcbi != null && string.Equals(fcbi.Tag as string, targetFg, StringComparison.OrdinalIgnoreCase))
                    {
                        fgIdx = i;
                        break;
                    }
                }
                _cmbDrawerFgMode.SelectedIndex = fgIdx;

                _chkDrawerFakeNvapi.IsChecked = game.UseFakeNvapi;
                _chkDrawerReFramework.IsChecked = game.InstallReFramework;
            }
            finally
            {
                _updatingDrawerControls = false;
            }

            UpdateDrawerMethodSummary();
        }

        private void OnDrawerMethodSelectionChanged()
        {
            if (_updatingDrawerControls || _selectedGame == null) return;
            var cbi = _cmbDrawerInstallMethod.SelectedItem as ComboBoxItem;
            if (cbi == null || cbi.Tag == null) return;

            string tag = cbi.Tag.ToString();
            if (tag == "direct" || tag == "dlss")
            {
                _selectedGame.Route = tag;
            }
            else if (tag.StartsWith("optiscaler:"))
            {
                _selectedGame.Route = "optiscaler";
                _selectedGame.OptiDllName = tag.Substring("optiscaler:".Length);
            }

            UpdateDrawerMethodSummary();
        }

        private void OnDrawerFgSelectionChanged()
        {
            if (_updatingDrawerControls || _selectedGame == null) return;
            var cbi = _cmbDrawerFgMode.SelectedItem as ComboBoxItem;
            if (cbi == null || cbi.Tag == null) return;

            string fgTag = cbi.Tag.ToString();
            _selectedGame.FgMode = fgTag;
            if (fgTag.StartsWith("dlssg_"))
            {
                _selectedGame.UseFakeNvapi = true;
                _updatingDrawerControls = true;
                _chkDrawerFakeNvapi.IsChecked = true;
                _updatingDrawerControls = false;
            }
            UpdateDrawerMethodSummary();
        }

        private void UpdateDrawerMethodSummary()
        {
            if (_selectedGame == null) return;

            bool isOpti = _selectedGame.Route == "optiscaler";
            string optiDll = string.IsNullOrEmpty(_selectedGame.OptiDllName) ? "dxgi.dll" : _selectedGame.OptiDllName;
            string fgMode = string.IsNullOrEmpty(_selectedGame.FgMode) ? "auto" : _selectedGame.FgMode;

            if (_panelDrawerFg != null)
                _panelDrawerFg.Visibility = isOpti ? Visibility.Visible : Visibility.Collapsed;
            _chkDrawerFakeNvapi.Visibility = isOpti ? Visibility.Visible : Visibility.Collapsed;

            _txtDrawerRoute.Text = _selectedGame.RouteDisplay;
            if (_selectedGame.InstallReFramework) _txtDrawerRoute.Text += " + REFramework";

            if (isOpti)
            {
                string fgNote = "";
                if (fgMode == "dlssg_xefg") fgNote = " Routes in-game DLSS Frame Generation to Intel XeSS-FG (AI optical flow on AMD/Intel).";
                else if (fgMode == "dlssg_fsrfg") fgNote = " Routes in-game DLSS Frame Generation to AMD FidelityFX Frame Generation.";
                else if (fgMode == "dlssg_nukems") fgNote = " Routes in-game DLSS Frame Generation via Nukem's dlssg-to-fsr3 swapchain.";
                else if (fgMode == "optifg_fsrfg") fgNote = " Enables Universal OptiFG + HUDFix using upscaler motion vectors & depth.";

                _txtDrawerMethodHint.Text = string.Format("Injects OptiScaler via {0} and routes DLSS/XeSS/FSR 2 inputs to HelixSR.{1} Press Insert in-game to open the OptiScaler menu.", optiDll, fgNote);
                _txtDrawerMethod.Text = _selectedGame.InstallReFramework
                    ? string.Format("{0} + REFramework Nightly (dinput8.dll)", _selectedGame.RouteDisplay)
                    : string.Format("{0} (Select DLSS in game)", _selectedGame.RouteDisplay);
                _txtDrawerGuide.Text = string.Format(
                    "1. Choose your preferred OptiScaler hook ({0}) and Frame Generation mode, then click '{1}'.\n" +
                    "2. Start the game and open Graphics / Display settings.\n" +
                    "3. Select NVIDIA DLSS as your upscaler (and enable DLSS Frame Generation if using a DLSS-G hook).\n" +
                    "4. Press the Insert key in-game to open OptiScaler's HUD and customize HelixSR & Frame Generation.",
                    optiDll, _selectedGame.Installed ? "Update / Reinstall" : "Install HelixSR");
            }
            else if (_selectedGame.Route == "dlss")
            {
                _txtDrawerMethodHint.Text = "EXPERIMENTAL (HelixSR 1.8.1): puts HelixSR's DLSS loader (dxgi.dll) and HelixSR as nvngx.dll next to the game's .exe, so the game's own DLSS option runs HelixSR without OptiScaler. Tested in very few games, Linux (Proton) only, NOT on Windows. May not work or may crash the game. Never use it in online games or games with anti-cheat (ban risk).";
                _txtDrawerMethod.Text = _selectedGame.InstallReFramework
                    ? "DLSS Loader (Experimental) + REFramework Nightly (dinput8.dll)"
                    : "DLSS Loader (Experimental — select DLSS in game)";
                _txtDrawerGuide.Text = string.Format(
                    "1. Click '{0}' above (you will be asked to confirm the experimental warning).\n" +
                    "2. Start the game and open Graphics / Display settings.\n" +
                    "3. Select NVIDIA DLSS. Leave NVIDIA-only options (Reflex, Frame Generation) off.\n" +
                    "4. If it misbehaves, switch back to Direct FSR 3.1 or OptiScaler and reinstall (or Restore / Uninstall).",
                    _selectedGame.Installed ? "Update / Reinstall" : "Install HelixSR");
            }
            else
            {
                bool hasNativeFsr = _selectedGame.FsrTargets != null && _selectedGame.FsrTargets.Count > 0;
                _txtDrawerMethodHint.Text = hasNativeFsr
                    ? string.Format("Replaces {0} native FidelityFX DX12 DLL(s) directly (*.original.dll backed up). Best stability for RE Engine & AMD GPUs.", _selectedGame.FsrTargets.Count)
                    : "Deploys standalone amd_fidelityfx_upscaler_dx12.dll & amd_fidelityfx_dx12.dll directly next to the game executable.";
                _txtDrawerMethod.Text = _selectedGame.InstallReFramework
                    ? "Direct FSR 3.1 Replacement + REFramework Nightly (dinput8.dll)"
                    : "Direct FSR 3.1 DLL Replacement (*.original.dll kept)";
                _txtDrawerGuide.Text = string.Format(
                    "1. Click '{0}' above to replace the FidelityFX upscaler DLL with HelixSR.\n" +
                    "2. Start the game and open Graphics / Display settings.\n" +
                    "3. Enable AMD FSR 3 / FSR 3.1 in the game's options menu.\n" +
                    "4. HelixSR will run automatically in place of FSR 3.1 with zero proxy hook overhead.",
                    _selectedGame.Installed ? "Update / Reinstall" : "Install HelixSR");
            }
        }

        private void OpenDrawer(GameInfo game)
        {
            bool wasClosed = _drawerPanel.Visibility != Visibility.Visible;
            _selectedGame = game;
            _txtDrawerTitle.Text = game.Name;
            _txtDrawerPlatform.Text = game.Launcher;
            _txtDrawerStatus.Text = game.Installed ? string.Format("✔ Installed ({0})", game.Version) : "Not Installed";
            _txtDrawerStatus.Foreground = game.Installed ? AccentEmerald : TextDim;

            _btnDrawerInstall.Content = game.Installed ? "⚡ Update / Reinstall" : "⚡ Install HelixSR";
            _btnDrawerUninstall.Visibility = game.Installed ? Visibility.Visible : Visibility.Collapsed;

            _txtDrawerExe.Text = game.ExeName ?? "N/A";
            _txtDrawerFolder.Text = game.ExeFolder ?? game.Folder;
            var apis = new List<string>(game.Inputs);
            if (game.FsrTargets != null && game.FsrTargets.Count > 0 && !apis.Contains("FSR 3.1")) apis.Add("FSR 3.1");
            _txtDrawerInputs.Text = apis.Count > 0 ? string.Join(", ", apis.ToArray()) : "DirectX 12";

            PopulateDrawerMethodOptions(game);

            // Load Thumb & Hero Artwork
            LoadArtworkAsync(game.LocalCoverPath, game.RemoteCoverUrl, game.AppId, "cover", _imgDrawerThumb, null);
            LoadArtworkAsync(game.LocalHeroPath, game.RemoteHeroUrl, game.AppId, "hero", _imgDrawerHero, null);

            // Load INI & Logs
            _txtIniEditor.Text = Engine.ReadOptiScalerIni(game.ExeFolder ?? game.Folder);
            RefreshLogs();

            _drawerPanel.Visibility = Visibility.Visible;

            if (wasClosed)
            {
                var tt = _drawerPanel.RenderTransform as TranslateTransform;
                if (tt != null)
                {
                    var slide = new DoubleAnimation(48, 0, TimeSpan.FromMilliseconds(200))
                    {
                        EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                    };
                    tt.BeginAnimation(TranslateTransform.XProperty, slide);
                }
            }
        }

        private void CloseDrawer()
        {
            _drawerPanel.Visibility = Visibility.Collapsed;
            _selectedGame = null;
        }

        private void RefreshLogs()
        {
            if (_selectedGame != null)
            {
                string target = _selectedGame.ExeFolder ?? _selectedGame.Folder;
                string l1 = Engine.ReadGameLog(target, "helixsr.log");
                string l2 = Engine.ReadGameLog(target, "OptiScaler.log");
                _txtLogOutput.Text = string.Format("=== helixsr.log ===\n{0}\n\n=== OptiScaler.log ===\n{1}", l1, l2);
            }
        }

        private void OnInstallClicked()
        {
            if (_selectedGame == null) return;

            var coreStatus = Engine.GetCoreStatus();
            if (!coreStatus.WeightsBuilt)
            {
                var res = MessageBox.Show(this,
                    "The HelixSR network has not been built yet (HelixSR 1.8+ builds it into amd_fidelityfx_dx12.dll).\n\n" +
                    "Without the network, HelixSR cannot upscale and the game may fail to start.\n\n" +
                    "Would you like to switch to the 'Engine & Weights' tab to build it now?",
                    "Network Not Built", MessageBoxButton.YesNo, MessageBoxImage.Warning);

                if (res == MessageBoxResult.Yes)
                {
                    SwitchTab("core");
                    return;
                }
            }

            if (_selectedGame.Route == "dlss")
            {
                var confirm = MessageBox.Show(this,
                    "EXPERIMENTAL: DLSS without OptiScaler (HelixSR 1.8.1)\n\n" +
                    "• Tested in very few games, on Linux (Proton) only — NOT tested on Windows.\n" +
                    "• It may not work or may crash the game.\n" +
                    "• Do NOT use it in online games or games with anti-cheat (ban risk).\n" +
                    "• Leave NVIDIA-only options (Reflex, Frame Generation) off.\n\n" +
                    "Install the DLSS loader for " + _selectedGame.Name + " anyway?",
                    "Experimental DLSS Loader", MessageBoxButton.YesNo, MessageBoxImage.Warning, MessageBoxResult.No);
                if (confirm != MessageBoxResult.Yes) return;
            }

            try
            {
                string targetFolder = _selectedGame.Folder;
                string chosenMethod = _selectedGame.RouteDisplay;
                bool withRef = _selectedGame.InstallReFramework;
                Engine.InstallHelixSR(_selectedGame);
                string msg = withRef
                    ? string.Format("Successfully installed HelixSR [{0}] + REFramework Nightly (dinput8.dll) for {1}!", chosenMethod, _selectedGame.Name)
                    : string.Format("Successfully installed HelixSR [{0}] for {1}!", chosenMethod, _selectedGame.Name);
                ShowToast(string.Format("Installed HelixSR [{0}] on {1}", chosenMethod, _selectedGame.Name));
                MessageBox.Show(this, msg, "Install Success", MessageBoxButton.OK, MessageBoxImage.Information);
                RefreshGames();

                GameInfo updated = null;
                foreach (var g in _allGames)
                {
                    if (string.Equals(g.Folder, targetFolder, StringComparison.OrdinalIgnoreCase))
                    {
                        updated = g;
                        break;
                    }
                }
                OpenDrawer(updated ?? _selectedGame);
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, string.Format("Install failed: {0}", ex.Message), "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void OnUninstallClicked()
        {
            if (_selectedGame == null) return;
            bool hasRef = _selectedGame.IsReEngine || _selectedGame.InstallReFramework;
            string confirmMsg = hasRef
                ? string.Format("Restore original files and uninstall HelixSR & REFramework from {0}?", _selectedGame.Name)
                : string.Format("Restore original files and uninstall HelixSR from {0}?", _selectedGame.Name);
            if (MessageBox.Show(this, confirmMsg, "Confirm Uninstall", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
                return;

            try
            {
                string targetFolder = _selectedGame.Folder;
                Engine.UninstallHelixSR(_selectedGame);
                string doneMsg = hasRef
                    ? string.Format("Restored original files and removed HelixSR & REFramework from {0}.", _selectedGame.Name)
                    : string.Format("Restored original files for {0}.", _selectedGame.Name);
                ShowToast(string.Format("Restored original files for {0}", _selectedGame.Name));
                MessageBox.Show(this, doneMsg, "Success", MessageBoxButton.OK, MessageBoxImage.Information);
                RefreshGames();

                GameInfo updated = null;
                foreach (var g in _allGames)
                {
                    if (string.Equals(g.Folder, targetFolder, StringComparison.OrdinalIgnoreCase))
                    {
                        updated = g;
                        break;
                    }
                }
                OpenDrawer(updated ?? _selectedGame);
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, string.Format("Uninstall failed: {0}", ex.Message), "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void OnLaunchClicked()
        {
            if (_selectedGame == null) return;
            try
            {
                if (!string.IsNullOrEmpty(_selectedGame.AppId))
                {
                    Process.Start(string.Format("steam://run/{0}", _selectedGame.AppId));
                    ShowToast("Launching " + _selectedGame.Name + " via Steam...");
                }
                else if (!string.IsNullOrEmpty(_selectedGame.ExeName) && !string.IsNullOrEmpty(_selectedGame.ExeFolder))
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = Path.Combine(_selectedGame.ExeFolder, _selectedGame.ExeName),
                        WorkingDirectory = _selectedGame.ExeFolder
                    });
                    ShowToast("Launching " + _selectedGame.Name + "...");
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, string.Format("Could not launch game: {0}", ex.Message), "Error", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        }

        private void OnClearShaderCacheClicked()
        {
            if (_selectedGame == null) return;
            try
            {
                bool res = Engine.ClearShaderCache(_selectedGame);
                if (res)
                {
                    ShowToast("Cleared shader cache for " + _selectedGame.Name);
                    MessageBox.Show(this, string.Format("Shader cache files successfully cleared for {0}!\n\nBroken or corrupted pipeline states (such as shader.cache2) were removed. The game will perform a clean shader compilation on next startup.", _selectedGame.Name), "Cache Cleared", MessageBoxButton.OK, MessageBoxImage.Information);
                }
                else
                {
                    MessageBox.Show(this, string.Format("No cached shader or pipeline binary files were found for {0}.", _selectedGame.Name), "Cache Empty", MessageBoxButton.OK, MessageBoxImage.Information);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, string.Format("Failed to clear cache: {0}", ex.Message), "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void OnSaveIniClicked()
        {
            if (_selectedGame == null) return;
            try
            {
                Engine.SaveOptiScalerIni(_selectedGame.ExeFolder ?? _selectedGame.Folder, _txtIniEditor.Text);
                ShowToast("Saved OptiScaler.ini for " + _selectedGame.Name);
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, string.Format("Failed to save: {0}", ex.Message), "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }
        #endregion

        #region Other Panes (Core, my-fsr, Settings, About)
        private Grid BuildCorePane()
        {
            var grid = new Grid { Margin = new Thickness(24) };
            var scroll = new ScrollViewer { VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
            var stack = new StackPanel { MaxWidth = 880, HorizontalAlignment = HorizontalAlignment.Left };

            stack.Children.Add(new TextBlock
            {
                Text = "HelixSR Core & Neural Network Compiler",
                FontSize = 21,
                FontWeight = FontWeights.Bold,
                Foreground = TextMain,
                Margin = new Thickness(0, 0, 0, 6)
            });
            stack.Children.Add(new TextBlock
            {
                Text = string.Format("HelixSR runs NVIDIA DLSS Model E neural networks as pure Direct3D 12 compute shaders. Since Core {0} the network is built locally once and embedded into HelixSR's DLL (one file per game).", Engine.CoreVersion),
                FontSize = 13,
                Foreground = TextMuted,
                TextWrapping = TextWrapping.Wrap,
                Margin = new Thickness(0, 0, 0, 20)
            });

            // Status Card
            var cardStatus = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(14),
                Padding = new Thickness(20),
                Margin = new Thickness(0, 0, 0, 18)
            };
            var sStack = new StackPanel();
            sStack.Children.Add(new TextBlock { Text = "Network Artifacts Telemetry", FontSize = 15, FontWeight = FontWeights.Bold, Foreground = TextMain, Margin = new Thickness(0, 0, 0, 12) });

            _txtWeightsStatus = new TextBlock { Text = "Checking...", FontSize = 13.5, FontWeight = FontWeights.Bold, Foreground = AccentEmerald, Margin = new Thickness(0, 0, 0, 8) };
            _txtWeightsSize = new TextBlock { Text = "Weights: -", FontSize = 12, Foreground = TextMuted, Margin = new Thickness(0, 0, 0, 4) };
            _txtKernelsSize = new TextBlock { Text = "Kernels: -", FontSize = 12, Foreground = TextMuted, Margin = new Thickness(0, 0, 0, 4) };
            _txtToolchainStatus = new TextBlock { Text = "Local Toolchain: -", FontSize = 12, Foreground = TextMuted, Margin = new Thickness(0, 0, 0, 4) };

            sStack.Children.Add(_txtWeightsStatus);
            sStack.Children.Add(_txtWeightsSize);
            sStack.Children.Add(_txtKernelsSize);
            sStack.Children.Add(_txtToolchainStatus);
            cardStatus.Child = sStack;
            stack.Children.Add(cardStatus);

            // Compiler Wizard Card
            var cardBuilder = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(14),
                Padding = new Thickness(20)
            };
            var bStack = new StackPanel();
            bStack.Children.Add(new TextBlock { Text = "Network Compiler Wizard", FontSize = 15, FontWeight = FontWeights.Bold, Foreground = TextMain, Margin = new Thickness(0, 0, 0, 8) });
            bStack.Children.Add(new TextBlock
            {
                Text = "Select an existing local copy of nvngx_dlss.dll (DLSS 310.7.0 found in your games) or download automatically from NVIDIA GitHub.",
                FontSize = 12,
                Foreground = TextMuted,
                Margin = new Thickness(0, 0, 0, 14)
            });

            _cmbDlssSource = new ComboBox { Height = 36, Margin = new Thickness(0, 0, 0, 12) };
            _cmbDlssSource.Items.Add("Download automatically from NVIDIA GitHub");
            _cmbDlssSource.SelectedIndex = 0;

            // HelixSR 1.8.0+ always builds both the 32- and 64-lane shaders; the DLL picks per GPU at run time
            _chkWave64 = new System.Windows.Controls.CheckBox
            {
                Content = "Wave32 + Wave64 shaders (RDNA 1–4) — always built since Core 1.8.0, picked per GPU at run time",
                Foreground = TextMain,
                FontSize = 12,
                IsChecked = true,
                IsEnabled = false,
                Margin = new Thickness(0, 0, 0, 16)
            };

            _btnStartBuild = CreateButton("⚡ Compile HelixSR Network & Auto-Sync", AccentEmeraldStrong, TextOnAccent, delegate { StartNetworkCompilation(); });
            _btnStartBuild.Height = 40;
            _btnStartBuild.HorizontalAlignment = HorizontalAlignment.Left;
            _btnStartBuild.Padding = new Thickness(20, 0, 20, 0);
            _btnStartBuild.Margin = new Thickness(0, 0, 0, 16);

            _txtCompileConsole = new TextBox
            {
                Height = 190,
                Background = new SolidColorBrush(Color.FromRgb(8, 10, 15)),
                Foreground = new SolidColorBrush(Color.FromRgb(241, 196, 15)),
                BorderBrush = BorderColor,
                FontFamily = new FontFamily("Consolas, Courier New"),
                FontSize = 11.5,
                Padding = new Thickness(10),
                IsReadOnly = true,
                AcceptsReturn = true,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                Text = "Ready to compile. Press 'Compile HelixSR Network & Auto-Sync' to build the network into HelixSR's DLL."
            };

            bStack.Children.Add(_cmbDlssSource);
            bStack.Children.Add(_chkWave64);
            bStack.Children.Add(_btnStartBuild);
            bStack.Children.Add(_txtCompileConsole);
            cardBuilder.Child = bStack;
            stack.Children.Add(cardBuilder);

            scroll.Content = stack;
            grid.Children.Add(scroll);
            return grid;
        }

        private Grid BuildMyFsrPane()
        {
            var grid = new Grid { Margin = new Thickness(24) };
            var stack = new StackPanel { MaxWidth = 880, HorizontalAlignment = HorizontalAlignment.Left };

            stack.Children.Add(new TextBlock { Text = "Custom FSR & Frame Generation Manager (my-fsr)", FontSize = 21, FontWeight = FontWeights.Bold, Foreground = TextMain, Margin = new Thickness(0, 0, 0, 6) });
            stack.Children.Add(new TextBlock
            {
                Text = "OptiScaler allows dropping custom AMD FidelityFX and Intel XeSS Frame Generation DLLs into 'my-fsr' to expose them in-game alongside HelixSR!",
                FontSize = 13,
                Foreground = TextMuted,
                Margin = new Thickness(0, 0, 0, 20)
            });

            var card = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(14),
                Padding = new Thickness(22)
            };
            var cStack = new StackPanel();
            cStack.Children.Add(new TextBlock
            {
                Text = "How to use custom FSR & Frame Generation DLLs in your games:\n\n" +
                       "1. Click 'Open Core my-fsr Folder' below (or open a game's 'my-fsr' folder from the Game Drawer).\n" +
                       "2. Drop any of these optional DLLs into the folder:\n" +
                       "   • amd_fidelityfx_upscaler_dx12.dll — Custom FSR 3.1 / FSR 4 upscaler for real-time A/B comparisons\n" +
                       "   • libxess_fg.dll & libxell.dll — Intel XeSS Frame Generation & XeLL Low Latency (for DLSS-G → XeFG)\n" +
                       "   • amd_fidelityfx_framegeneration_dx12.dll — AMD FidelityFX Frame Generation (for DLSS-G → FSR-FG / OptiFG)\n" +
                       "   • dlssg_to_fsr3_amd_is_better.dll — Nukem's DLSS-G to FSR 3.1 Streamline swapchain translator\n" +
                       "3. Select your desired Frame Generation mode in the Game Drawer and install HelixSR.\n" +
                       "4. Launch the game and press the Insert key to open OptiScaler's HUD to switch upscalers or tune Frame Gen!",
                FontSize = 13,
                Foreground = TextMain,
                TextWrapping = TextWrapping.Wrap,
                LineHeight = 22
            });

            var btnOpenCoreMyFsr = CreateButton("📂 Open Core my-fsr Folder", AccentEmeraldStrong, TextOnAccent, delegate
            {
                string p = Path.Combine(Engine.CoreDir, "my-fsr");
                if (!Directory.Exists(p)) { try { Directory.CreateDirectory(p); } catch { } }
                if (Directory.Exists(p)) OpenFolderInExplorer(p);
            });
            btnOpenCoreMyFsr.HorizontalAlignment = HorizontalAlignment.Left;
            btnOpenCoreMyFsr.Margin = new Thickness(0, 20, 0, 0);
            cStack.Children.Add(btnOpenCoreMyFsr);

            card.Child = cStack;
            stack.Children.Add(card);

            grid.Children.Add(stack);
            return grid;
        }

        private Grid BuildSettingsPane()
        {
            var grid = new Grid { Margin = new Thickness(24) };
            var stack = new StackPanel { MaxWidth = 880, HorizontalAlignment = HorizontalAlignment.Left };

            stack.Children.Add(new TextBlock { Text = "Settings & Library Scan Paths", FontSize = 21, FontWeight = FontWeights.Bold, Foreground = TextMain, Margin = new Thickness(0, 0, 0, 20) });

            var card = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(14),
                Padding = new Thickness(22)
            };
            var cStack = new StackPanel();
            cStack.Children.Add(new TextBlock { Text = "Detected Steam Library Roots:", FontSize = 14, FontWeight = FontWeights.Bold, Foreground = TextMain, Margin = new Thickness(0, 0, 0, 8) });

            foreach (var lib in Engine.GetSteamLibraries())
            {
                cStack.Children.Add(new TextBlock { Text = "• " + lib, FontSize = 12.5, Foreground = TextMuted, Margin = new Thickness(0, 3, 0, 3) });
            }

            cStack.Children.Add(new TextBlock { Text = "Custom Scan Folders:", FontSize = 14, FontWeight = FontWeights.Bold, Foreground = TextMain, Margin = new Thickness(0, 18, 0, 8) });
            if (_customFolders.Count == 0)
            {
                cStack.Children.Add(new TextBlock { Text = "(No custom folders added yet. Click '＋ Add Game' or drag & drop any game folder onto the window).", FontSize = 12.5, Foreground = TextDim });
            }
            else
            {
                foreach (var f in _customFolders)
                {
                    cStack.Children.Add(new TextBlock { Text = "• " + f, FontSize = 12.5, Foreground = TextMuted, Margin = new Thickness(0, 3, 0, 3) });
                }
            }

            var btnAdd = CreateButton("＋ Add Custom Folder", AccentEmeraldStrong, TextOnAccent, delegate { AddCustomGameFolder(); });
            btnAdd.HorizontalAlignment = HorizontalAlignment.Left;
            btnAdd.Margin = new Thickness(0, 18, 0, 0);
            cStack.Children.Add(btnAdd);

            card.Child = cStack;
            stack.Children.Add(card);
            grid.Children.Add(stack);
            return grid;
        }

        private Grid BuildAboutPane()
        {
            var grid = new Grid { Margin = new Thickness(24) };
            var stack = new StackPanel { MaxWidth = 880, HorizontalAlignment = HorizontalAlignment.Left };

            stack.Children.Add(new TextBlock { Text = "Diagnostics & Hardware Telemetry", FontSize = 21, FontWeight = FontWeights.Bold, Foreground = TextMain, Margin = new Thickness(0, 0, 0, 20) });

            var card = new Border
            {
                Background = BgCard,
                BorderBrush = BorderColor,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(14),
                Padding = new Thickness(22)
            };
            var cStack = new StackPanel();
            cStack.Children.Add(new TextBlock { Text = "Detected Display Adapters:", FontSize = 14, FontWeight = FontWeights.Bold, Foreground = TextMain, Margin = new Thickness(0, 0, 0, 10) });

            foreach (var g in Engine.GetGpuInfo())
            {
                var r = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 4) };
                r.Children.Add(new TextBlock { Text = "⚡ " + g.Name, FontSize = 12.5, FontWeight = FontWeights.SemiBold, Foreground = TextMain, Width = 340 });
                r.Children.Add(new TextBlock { Text = g.RamMB > 0 ? string.Format("{0} MB VRAM", g.RamMB) : "Shared / Unified APU Memory", FontSize = 12.5, Foreground = AccentEmerald, Width = 190 });
                r.Children.Add(new TextBlock { Text = string.Format("Driver: {0}", g.Driver), FontSize = 12, Foreground = TextDim });
                cStack.Children.Add(r);
            }

            cStack.Children.Add(new TextBlock
            {
                Text = "\nAbout HelixSR Manager:\nHelixSR runs NVIDIA's DLSS Model E neural network using pure Direct3D 12 compute shaders on AMD RDNA GPUs without Tensor Cores or NVIDIA drivers.\n\nHelixSR Manager is a 100% standalone native desktop application supporting Direct FSR 3.1 replacement, OptiScaler proxy hooks, DLSS-G Frame Generation translation (XeFG / FSR-FG / NukemFG / OptiFG), FakeNVAPI, and automatic Capcom REFramework nightly deployment.\n\nOpen Source / Fork Notice:\nDenarmo is not the original owner of the underlying forked codebase. Modifications and contributions in this fork are provided under the MIT License and may be used by others.",
                FontSize = 12.5,
                Foreground = TextMuted,
                TextWrapping = TextWrapping.Wrap,
                LineHeight = 20
            });

            card.Child = cStack;
            stack.Children.Add(card);
            grid.Children.Add(stack);
            return grid;
        }
        #endregion

        #region Logic & Event Handlers
        private void RefreshGames()
        {
            _allGames = Engine.ScanAllGames(_customFolders);
            if (_txtGameCountBadge != null) _txtGameCountBadge.Text = _allGames.Count.ToString();
            UpdateFilterCounts();
            FilterGames();
            UpdateDlssCandidates();
        }

        private void UpdateFilterCounts()
        {
            int total = _allGames.Count;
            int active = 0;
            int uninstalled = 0;
            int direct = 0;
            int opti = 0;
            int reEngine = 0;

            foreach (var g in _allGames)
            {
                if (g.Installed) active++; else uninstalled++;
                if (g.Route == "direct") direct++; else opti++;
                if (g.IsReEngine) reEngine++;
            }

            if (_txtStatTotal != null) _txtStatTotal.Text = total.ToString();
            if (_txtStatActive != null) _txtStatActive.Text = active.ToString();
            if (_txtStatDirect != null) _txtStatDirect.Text = direct.ToString();
            if (_txtStatOpti != null) _txtStatOpti.Text = opti.ToString();

            SetPillCount("all", "All Games", total);
            SetPillCount("installed", "⚡ HelixSR Active", active);
            SetPillCount("uninstalled", "○ Not Installed", uninstalled);
            SetPillCount("direct", "🎯 Direct FSR 3.1", direct);
            SetPillCount("optiscaler", "🔌 OptiScaler Hook", opti);
            SetPillCount("reengine", "🧬 Capcom RE Engine", reEngine);
        }

        private void SetPillCount(string key, string baseLabel, int count)
        {
            if (_filterPillButtons.ContainsKey(key))
            {
                _filterPillButtons[key].Content = string.Format("{0} ({1})", baseLabel, count);
            }
        }

        private void FilterGames()
        {
            if (_txtSearch == null) return;
            string q = _txtSearch.Text.Trim().ToLowerInvariant();
            string l = _cmbLauncher != null && _cmbLauncher.SelectedItem != null ? _cmbLauncher.SelectedItem.ToString() : "All Launchers";
            string s = _cmbStatus != null && _cmbStatus.SelectedItem != null ? _cmbStatus.SelectedItem.ToString() : "All Status";
            string sort = _cmbSort != null && _cmbSort.SelectedItem != null ? _cmbSort.SelectedItem.ToString() : "Name (A-Z)";

            var filtered = new List<GameInfo>();
            foreach (var g in _allGames)
            {
                if (!string.IsNullOrEmpty(q))
                {
                    bool matchName = g.Name != null && g.Name.ToLowerInvariant().Contains(q);
                    bool matchFolder = g.Folder != null && g.Folder.ToLowerInvariant().Contains(q);
                    bool matchRoute = g.RouteDisplay != null && g.RouteDisplay.ToLowerInvariant().Contains(q);
                    if (!matchName && !matchFolder && !matchRoute) continue;
                }
                if (l == "Steam" && g.Launcher != "Steam") continue;
                if (l == "Custom" && g.Launcher != "Custom") continue;
                if ((s == "HelixSR Active" || s == "HelixSR Installed") && !g.Installed) continue;
                if (s == "Not Installed" && g.Installed) continue;

                // Quick Filter Pill check
                if (_quickFilter == "installed" && !g.Installed) continue;
                if (_quickFilter == "uninstalled" && g.Installed) continue;
                if (_quickFilter == "direct" && g.Route != "direct") continue;
                if (_quickFilter == "optiscaler" && g.Route != "optiscaler") continue;
                if (_quickFilter == "reengine" && !g.IsReEngine) continue;

                filtered.Add(g);
            }

            if (sort == "Name (A-Z)")
                filtered.Sort(delegate(GameInfo a, GameInfo b) { return string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase); });
            else if (sort == "Name (Z-A)")
                filtered.Sort(delegate(GameInfo a, GameInfo b) { return string.Compare(b.Name, a.Name, StringComparison.OrdinalIgnoreCase); });
            else if (sort == "Installed First")
                filtered.Sort(delegate(GameInfo a, GameInfo b) { return b.Installed.CompareTo(a.Installed); });

            RenderGames(filtered);
        }

        private void RenderGames(List<GameInfo> list)
        {
            _currentRenderedGames = list ?? new List<GameInfo>();
            _gridWrapPanel.Children.Clear();
            _listGamesView.ItemsSource = list;
            if (_emptyStatePanel != null)
            {
                _emptyStatePanel.Visibility = list.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
            }

            foreach (var g in list)
            {
                var card = BuildGameCard(g);
                _gridWrapPanel.Children.Add(card);
            }

            if (_isHandheldMode && _currentRenderedGames.Count > 0)
            {
                UpdateGamepadFocus(_focusedGameIndex >= 0 ? _focusedGameIndex : 0);
            }
        }

        private Border BuildGameCard(GameInfo game)
        {
            var scaleTrans = new ScaleTransform(1.0, 1.0);
            var translateTrans = new TranslateTransform(0, 0);
            var transformGroup = new TransformGroup();
            transformGroup.Children.Add(scaleTrans);
            transformGroup.Children.Add(translateTrans);

            var cardShadow = new DropShadowEffect
            {
                Color = Colors.Black,
                BlurRadius = 16,
                ShadowDepth = 5,
                Opacity = _isLightTheme ? 0.12 : 0.48
            };

            var card = new Border
            {
                Tag = game,
                Width = 204,
                Height = 304,
                CornerRadius = new CornerRadius(14),
                Background = BgCard,
                BorderBrush = game.Installed ? AccentEmerald : BorderColor,
                BorderThickness = new Thickness(game.Installed ? 2 : 1),
                Margin = new Thickness(9),
                Cursor = Cursors.Hand,
                RenderTransformOrigin = new Point(0.5, 0.5),
                RenderTransform = transformGroup,
                Effect = cardShadow
            };

            var innerClip = new Border
            {
                CornerRadius = new CornerRadius(12),
                ClipToBounds = true
            };

            var grid = new Grid();

            // Fallback Title Container
            var fallback = new Border
            {
                Background = new LinearGradientBrush(Color.FromRgb(26, 33, 46), Color.FromRgb(14, 18, 26), 45)
            };
            var fTxt = new TextBlock
            {
                Text = game.Name,
                FontWeight = FontWeights.Bold,
                FontSize = 14,
                Foreground = Brushes.White,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                TextWrapping = TextWrapping.Wrap,
                TextAlignment = TextAlignment.Center,
                Margin = new Thickness(14)
            };
            fallback.Child = fTxt;
            grid.Children.Add(fallback);

            // Cover Image
            var img = new Image { Stretch = Stretch.UniformToFill };
            grid.Children.Add(img);

            LoadArtworkAsync(game.LocalCoverPath, game.RemoteCoverUrl, game.AppId, "cover", img, fallback);

            // Top Badges
            var topPanel = new WrapPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Left,
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(9)
            };
            var platBadge = new Border
            {
                Background = new SolidColorBrush(Color.FromArgb(205, 8, 12, 18)),
                BorderBrush = new SolidColorBrush(Color.FromArgb(50, 255, 255, 255)),
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(6),
                Padding = new Thickness(6, 2, 6, 2),
                Margin = new Thickness(0, 0, 4, 4)
            };
            platBadge.Child = new TextBlock { Text = game.Launcher, FontSize = 9.5, FontWeight = FontWeights.Bold, Foreground = Brushes.White };
            topPanel.Children.Add(platBadge);

            foreach (var inp in game.Inputs)
            {
                Brush badgeBg = AccentViolet;
                Brush badgeFg = Brushes.White;
                if (inp == "DLSS") { badgeBg = AccentEmeraldStrong; badgeFg = TextOnAccent; }
                else if (inp == "DLSS-G") { badgeBg = AccentAmber; badgeFg = TextOnAccent; }
                else if (inp == "XeSS") { badgeBg = AccentSky; badgeFg = Brushes.White; }

                var b = new Border
                {
                    Background = badgeBg,
                    CornerRadius = new CornerRadius(6),
                    Padding = new Thickness(6, 2, 6, 2),
                    Margin = new Thickness(0, 0, 4, 4)
                };
                b.Child = new TextBlock { Text = inp, FontSize = 9.5, FontWeight = FontWeights.Bold, Foreground = badgeFg };
                topPanel.Children.Add(b);
            }

            if (game.IsReEngine)
            {
                var reBadge = new Border
                {
                    Background = new SolidColorBrush(Color.FromArgb(220, 180, 40, 40)),
                    CornerRadius = new CornerRadius(6),
                    Padding = new Thickness(6, 2, 6, 2),
                    Margin = new Thickness(0, 0, 4, 4)
                };
                reBadge.Child = new TextBlock { Text = "RE", FontSize = 9.5, FontWeight = FontWeights.Bold, Foreground = Brushes.White };
                topPanel.Children.Add(reBadge);
            }
            grid.Children.Add(topPanel);

            // Hover Quick-Action Pill Overlay
            var hoverBadge = new Border
            {
                Background = new SolidColorBrush(Color.FromArgb(225, 12, 16, 24)),
                BorderBrush = AccentEmerald,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(8),
                Padding = new Thickness(10, 5, 10, 5),
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Opacity = 0,
                IsHitTestVisible = false
            };
            hoverBadge.Child = new TextBlock
            {
                Text = game.Installed ? "⚙️ Configure HelixSR" : "⚡ Setup & Install",
                FontSize = 11,
                FontWeight = FontWeights.Bold,
                Foreground = AccentEmerald
            };
            grid.Children.Add(hoverBadge);

            // Bottom Scrim / Details
            var bottomScrim = new Border
            {
                Background = new LinearGradientBrush(Colors.Transparent, Color.FromArgb(248, 8, 11, 16), 90),
                VerticalAlignment = VerticalAlignment.Bottom,
                Padding = new Thickness(12, 30, 12, 11)
            };
            var bStack = new StackPanel();

            var title = new TextBlock
            {
                Text = game.Name,
                FontWeight = FontWeights.Bold,
                FontSize = 12.5,
                Foreground = Brushes.White,
                TextTrimming = TextTrimming.CharacterEllipsis,
                Margin = new Thickness(0, 0, 0, 4)
            };

            var metaRow = new DockPanel();
            var routeTag = new TextBlock
            {
                Text = game.RouteDisplay,
                FontSize = 9.5,
                Foreground = new SolidColorBrush(Color.FromRgb(148, 163, 184)),
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Center
            };
            DockPanel.SetDock(routeTag, Dock.Right);
            metaRow.Children.Add(routeTag);

            var statusRow = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
            var statusDot = new Ellipse
            {
                Width = 6,
                Height = 6,
                Fill = game.Installed ? AccentEmerald : new SolidColorBrush(Color.FromRgb(100, 116, 139)),
                Margin = new Thickness(0, 0, 5, 0),
                VerticalAlignment = VerticalAlignment.Center
            };
            var status = new TextBlock
            {
                Text = game.Installed ? "Active" : "Not Installed",
                FontSize = 10.5,
                FontWeight = FontWeights.Bold,
                Foreground = game.Installed ? AccentEmerald : new SolidColorBrush(Color.FromRgb(148, 163, 184))
            };
            statusRow.Children.Add(statusDot);
            statusRow.Children.Add(status);
            metaRow.Children.Add(statusRow);

            bStack.Children.Add(title);
            bStack.Children.Add(metaRow);
            bottomScrim.Child = bStack;
            grid.Children.Add(bottomScrim);

            innerClip.Child = grid;
            card.Child = innerClip;

            // Smooth Reactive Hover Animations (Scale + Lift + Glow)
            card.MouseEnter += delegate
            {
                var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
                var dur = TimeSpan.FromMilliseconds(160);
                scaleTrans.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(1.035, dur) { EasingFunction = ease });
                scaleTrans.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(1.035, dur) { EasingFunction = ease });
                translateTrans.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(-4, dur) { EasingFunction = ease });
                hoverBadge.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(1.0, dur));
                card.BorderBrush = AccentEmerald;
            };

            card.MouseLeave += delegate
            {
                var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
                var dur = TimeSpan.FromMilliseconds(160);
                scaleTrans.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(1.0, dur) { EasingFunction = ease });
                scaleTrans.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(1.0, dur) { EasingFunction = ease });
                translateTrans.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(0, dur) { EasingFunction = ease });
                hoverBadge.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(0.0, dur));
                card.BorderBrush = game.Installed ? AccentEmerald : BorderColor;
            };

            card.MouseLeftButtonUp += delegate
            {
                OpenDrawer(game);
            };

            // Right-Click ContextMenu for instant actions
            var ctx = new ContextMenu();
            var miConfig = new MenuItem { Header = "⚙️  Configure & Choose Method..." };
            miConfig.Click += delegate { OpenDrawer(game); };
            ctx.Items.Add(miConfig);

            var miInstall = new MenuItem { Header = game.Installed ? "⚡  Update / Reinstall HelixSR" : "⚡  Quick Install HelixSR" };
            miInstall.Click += delegate { _selectedGame = game; OnInstallClicked(); };
            ctx.Items.Add(miInstall);

            if (game.Installed)
            {
                var miUninstall = new MenuItem { Header = "↩  Restore Original Files (Uninstall)" };
                miUninstall.Click += delegate { _selectedGame = game; OnUninstallClicked(); };
                ctx.Items.Add(miUninstall);
            }

            var miCache = new MenuItem { Header = "🧹  Clear Shader Cache" };
            miCache.Click += delegate { _selectedGame = game; OnClearShaderCacheClicked(); };
            ctx.Items.Add(miCache);

            var miLaunch = new MenuItem { Header = "▶  Launch Game" };
            miLaunch.Click += delegate { _selectedGame = game; OnLaunchClicked(); };
            ctx.Items.Add(miLaunch);

            var miFolder = new MenuItem { Header = "📁  Open Game Folder" };
            miFolder.Click += delegate { OpenFolderInExplorer(game.ExeFolder ?? game.Folder); };
            ctx.Items.Add(miFolder);

            var miCopyPath = new MenuItem { Header = "📋  Copy Folder Path" };
            miCopyPath.Click += delegate
            {
                try
                {
                    Clipboard.SetText(game.ExeFolder ?? game.Folder);
                    ShowToast("Copied path: " + (game.ExeFolder ?? game.Folder));
                }
                catch { }
            };
            ctx.Items.Add(miCopyPath);

            card.ContextMenu = ctx;
            return card;
        }

        private static BitmapImage LoadBitmapSync(string filePath)
        {
            var bmp = new BitmapImage();
            bmp.BeginInit();
            bmp.CacheOption = BitmapCacheOption.OnLoad;
            bmp.UriSource = new Uri(filePath);
            bmp.EndInit();
            bmp.Freeze();
            return bmp;
        }

        private void LoadArtworkAsync(string localPath, string remoteUrl, string appId, string kind, Image targetImage, UIElement fallbackElement)
        {
            if (targetImage == null) return;

            // 1. If local file exists, load immediately
            if (!string.IsNullOrEmpty(localPath) && File.Exists(localPath))
            {
                try
                {
                    targetImage.Source = LoadBitmapSync(localPath);
                    if (fallbackElement != null) fallbackElement.Visibility = Visibility.Collapsed;
                    return;
                }
                catch { }
            }

            // 2. If no remote URL or no appId, keep fallback visible
            if (string.IsNullOrEmpty(remoteUrl) || string.IsNullOrEmpty(appId))
            {
                if (fallbackElement != null) fallbackElement.Visibility = Visibility.Visible;
                return;
            }

            // Check cache directory
            string cacheDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HelixSR", "cache", "covers");
            string cacheFile = Path.Combine(cacheDir, string.Format("{0}_{1}.jpg", appId, kind));

            if (File.Exists(cacheFile))
            {
                try
                {
                    targetImage.Source = LoadBitmapSync(cacheFile);
                    if (fallbackElement != null) fallbackElement.Visibility = Visibility.Collapsed;
                    return;
                }
                catch { }
            }

            // 3. Background download with Steam CDN failover
            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    if (!Directory.Exists(cacheDir)) Directory.CreateDirectory(cacheDir);

                    string[] urls = new string[]
                    {
                        remoteUrl,
                        kind == "cover"
                            ? string.Format("https://cdn.cloudflare.steamstatic.com/steam/apps/{0}/library_600x900.jpg", appId)
                        : string.Format("https://cdn.cloudflare.steamstatic.com/steam/apps/{0}/library_hero.jpg", appId),
                        kind == "cover"
                            ? string.Format("https://steamcdn-a.akamaihd.net/steam/apps/{0}/library_600x900.jpg", appId)
                        : string.Format("https://steamcdn-a.akamaihd.net/steam/apps/{0}/library_hero.jpg", appId),
                        string.Format("https://cdn.cloudflare.steamstatic.com/steam/apps/{0}/header.jpg", appId)
                    };

                    byte[] data = null;
                    using (var wc = new WebClient())
                    {
                        wc.Headers.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36");
                        foreach (var url in urls)
                        {
                            try
                            {
                                data = wc.DownloadData(url);
                                if (data != null && data.Length > 1000) break;
                            }
                            catch { }
                        }
                    }

                    if (data != null && data.Length > 1000 && !_isClosing)
                    {
                        File.WriteAllBytes(cacheFile, data);

                        if (!_isClosing)
                        {
                            Dispatcher.BeginInvoke(new Action(delegate
                            {
                                if (_isClosing) return;
                                try
                                {
                                    targetImage.Source = LoadBitmapSync(cacheFile);
                                    if (fallbackElement != null) fallbackElement.Visibility = Visibility.Collapsed;
                                }
                                catch { }
                            }));
                        }
                    }
                }
                catch { }
            });
        }

        private void AddCustomGameFolder()
        {
            using (var dialog = new FolderBrowserDialog
            {
                Description = "Select a Game installation folder:"
            })
            {
                var res = dialog.ShowDialog();
                try { Environment.CurrentDirectory = Path.GetTempPath(); } catch { }
                if (res == System.Windows.Forms.DialogResult.OK)
                {
                    string p = Engine.NormalizePath(dialog.SelectedPath);
                    bool exists = false;
                    foreach (var cf in _customFolders)
                    {
                        if (string.Equals(Engine.NormalizePath(cf), p, StringComparison.OrdinalIgnoreCase))
                        {
                            exists = true;
                            break;
                        }
                    }
                    if (!string.IsNullOrEmpty(p) && Directory.Exists(p) && !exists)
                    {
                        _customFolders.Add(p);
                        SaveSettings();
                        RefreshGames();
                        ShowToast("Added folder: " + Path.GetFileName(p));
                    }
                }
            }
        }

        private void BatchInstall(bool install)
        {
            string act = install ? "Install HelixSR on all uninstalled games" : "Restore original files on all installed games";
            if (MessageBox.Show(this, string.Format("Are you sure you want to {0}?", act), "Batch Action", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes)
                return;

            int count = 0;
            foreach (var g in _allGames)
            {
                try
                {
                    if (install && !g.Installed && !string.IsNullOrEmpty(g.Route))
                    {
                        Engine.InstallHelixSR(g);
                        count++;
                    }
                    else if (!install && g.Installed)
                    {
                        Engine.UninstallHelixSR(g);
                        count++;
                    }
                }
                catch { }
            }

            ShowToast(string.Format("Batch operation completed on {0} game(s)", count));
            MessageBox.Show(this, string.Format("Operation complete on {0} games.", count), "Done", MessageBoxButton.OK, MessageBoxImage.Information);
            RefreshGames();
        }

        private void UpdateCoreStatus()
        {
            var st = Engine.GetCoreStatus();
            if (st.WeightsBuilt)
            {
                if (_dotCoreStatus != null) _dotCoreStatus.Fill = AccentEmerald;
                if (_dotSidebarCardStatus != null) _dotSidebarCardStatus.Fill = AccentEmerald;
                if (_txtSidebarCardStatus != null) _txtSidebarCardStatus.Text = "Ready • Network Built";
                if (_barSidebarProgress != null) _barSidebarProgress.Width = 195;

                _txtWeightsStatus.Foreground = AccentEmerald;
                if (st.NetworkEmbedded)
                {
                    _txtWeightsStatus.Text = string.Format("✔ Network: READY (embedded in amd_fidelityfx_dx12.dll, {0:F2} MB)", st.DllSize / (1024.0 * 1024.0));
                    _txtWeightsSize.Text = string.Format("Weights (embedded): {0:F2} MB", st.WeightsSize / (1024.0 * 1024.0));
                    _txtKernelsSize.Text = string.Format("DXIL kernels (embedded): {0:F2} MB", st.KernelsSize / (1024.0 * 1024.0));
                }
                else
                {
                    _txtWeightsStatus.Text = "✔ Network: READY (separate files from an older setup — rebuild to embed it)";
                    _txtWeightsSize.Text = string.Format("helixsr_weights.bin: {0:F2} MB", st.WeightsSize / (1024.0 * 1024.0));
                    _txtKernelsSize.Text = string.Format("helixsr_kernels.pak: {0:F2} MB", st.KernelsSize / (1024.0 * 1024.0));
                }
            }
            else
            {
                if (_dotCoreStatus != null) _dotCoreStatus.Fill = AccentAmber;
                if (_dotSidebarCardStatus != null) _dotSidebarCardStatus.Fill = AccentAmber;
                if (_txtSidebarCardStatus != null) _txtSidebarCardStatus.Text = "Action Needed • Build Network";
                if (_barSidebarProgress != null) _barSidebarProgress.Width = 65;

                _txtWeightsStatus.Text = "⚠ Network: NOT BUILT (Run Compiler below)";
                _txtWeightsStatus.Foreground = AccentAmber;
                _txtWeightsSize.Text = "Weights: Missing";
                _txtKernelsSize.Text = "DXIL kernels: Missing";
            }

            _txtToolchainStatus.Text = st.HasPython && st.HasDxc ? "Toolchain: Installed in LocalAppData" : "Toolchain: Will download automatically on first compile";
        }

        private void UpdateDlssCandidates()
        {
            if (_cmbDlssSource == null) return;
            _cmbDlssSource.Items.Clear();
            _cmbDlssSource.Items.Add("Download automatically from NVIDIA GitHub");
            foreach (var g in _allGames)
            {
                if (!string.IsNullOrEmpty(g.FoundNvngxDlssPath))
                {
                    _cmbDlssSource.Items.Add(string.Format("Use from {0} ({1})", g.Name, g.FoundNvngxDlssPath));
                }
            }
            _cmbDlssSource.SelectedIndex = _cmbDlssSource.Items.Count > 1 ? 1 : 0;
        }

        private void UpdateGpuInfo()
        {
            var gpus = Engine.GetGpuInfo();
            if (gpus.Count > 0 && _txtGpuFooter != null)
            {
                _txtGpuFooter.Text = gpus[0].Name;
            }
        }

        private void StartNetworkCompilation()
        {
            KillCompileProcess();
            _btnStartBuild.IsEnabled = false;
            _txtCompileConsole.Text = "Starting HelixSR Network compiler...\n";

            string ps1 = Path.Combine(Engine.CoreDir, "helixsr-setup.ps1");
            // HelixSR 1.8+ setup: -BuildOnly no longer exists; the game step that follows the build reads stdin, which is
            // closed below, so it exits right away (EOF) and the Manager handles the game installs itself.
            // Both wave sizes are always built since 1.8.0, so -Wave64 is not needed.
            var psScript = new System.Text.StringBuilder();
            psScript.Append("& '").Append(ps1.Replace("'", "''")).Append("' -Yes -Rebuild");

            if (_cmbDlssSource.SelectedIndex > 0)
            {
                string sel = _cmbDlssSource.SelectedItem.ToString();
                int idx = sel.IndexOf('(');
                int endIdx = sel.LastIndexOf(')');
                if (idx != -1 && endIdx != -1)
                {
                    string dlss = sel.Substring(idx + 1, endIdx - idx - 1);
                    psScript.Append(" -Dlss '").Append(dlss.Replace("'", "''")).Append("'");
                }
            }

            string encodedCommand = Convert.ToBase64String(System.Text.Encoding.Unicode.GetBytes(psScript.ToString()));

            var startInfo = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + encodedCommand,
                WorkingDirectory = Path.GetTempPath(),
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };
            startInfo.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";

            var proc = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
            _compileProc = proc;

            // Once upstream's interactive game step starts, its prompts are irrelevant here: hide them
            bool[] installerPhase = new bool[] { false };

            proc.OutputDataReceived += delegate(object s, DataReceivedEventArgs e)
            {
                if (!string.IsNullOrEmpty(e.Data) && !_isClosing)
                {
                    string line = e.Data;
                    bool announce = false;
                    if (!installerPhase[0] && line.IndexOf("looking for games", StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        installerPhase[0] = true;
                        announce = true;
                    }
                    else if (installerPhase[0])
                    {
                        return;
                    }

                    Dispatcher.BeginInvoke(new Action(delegate
                    {
                        if (_isClosing) return;
                        _txtCompileConsole.AppendText(announce
                            ? "[helixsr-manager] network build complete; install HelixSR per game from the Games Library.\n"
                            : line + "\n");
                        _txtCompileConsole.ScrollToEnd();
                    }));
                }
            };

            proc.ErrorDataReceived += delegate(object s, DataReceivedEventArgs e)
            {
                if (!string.IsNullOrEmpty(e.Data) && !_isClosing)
                {
                    Dispatcher.BeginInvoke(new Action(delegate
                    {
                        if (_isClosing) return;
                        _txtCompileConsole.AppendText("[ERR] " + e.Data + "\n");
                        _txtCompileConsole.ScrollToEnd();
                    }));
                }
            };

            proc.Exited += delegate
            {
                Interlocked.CompareExchange(ref _compileProc, null, proc);
                try { proc.Dispose(); } catch { }
                if (_isClosing) return;
                Dispatcher.BeginInvoke(new Action(delegate
                {
                    if (_isClosing) return;
                    _btnStartBuild.IsEnabled = true;
                    _txtCompileConsole.AppendText("\nCompilation process finished.\n");
                    UpdateCoreStatus();
                    int synced = Engine.SyncHelixSRToInstalledGames();
                    if (synced > 0)
                    {
                        _txtCompileConsole.AppendText(string.Format("Auto-synced the rebuilt HelixSR DLL to {0} installed game(s).\n", synced));
                        _txtCompileConsole.ScrollToEnd();
                        RefreshGames();
                    }
                    ShowToast("Network compilation finished");
                }));
            };

            proc.Start();
            try { proc.StandardInput.Close(); } catch { }
            proc.BeginOutputReadLine();
            proc.BeginErrorReadLine();
        }
        #endregion

        #region Handheld & Gamepad Controller Support
        public void ToggleHandheldMode(bool? forceEnable = null)
        {
            bool target = forceEnable.HasValue ? forceEnable.Value : !_isHandheldMode;
            if (_isHandheldMode == target) return;
            _isHandheldMode = target;

            if (_isHandheldMode)
            {
                _prevWindowStyle = WindowStyle;
                _prevWindowState = WindowState;
                _prevResizeMode = ResizeMode;

                WindowStyle = WindowStyle.None;
                ResizeMode = ResizeMode.NoResize;
                WindowState = WindowState.Normal;
                WindowState = WindowState.Maximized;

                if (_handheldLegendBar != null) _handheldLegendBar.Visibility = Visibility.Visible;
                if (_rootGrid != null) _rootGrid.Margin = new Thickness(8, 8, 8, 48);

                if (_btnHandheldToggle != null)
                {
                    _btnHandheldToggle.Content = "🎮 Handheld: ON";
                    _btnHandheldToggle.Background = AccentEmeraldBg;
                    _btnHandheldToggle.BorderBrush = AccentEmerald;
                }

                if (_focusedGameIndex < 0 && _currentRenderedGames != null && _currentRenderedGames.Count > 0)
                {
                    UpdateGamepadFocus(0);
                }

                ShowToast("🎮 Handheld Mode: ON (Fullscreen & Controller Navigation Active)");
            }
            else
            {
                WindowState = _prevWindowState != WindowState.Minimized ? _prevWindowState : WindowState.Normal;
                WindowStyle = _prevWindowStyle != WindowStyle.None ? _prevWindowStyle : WindowStyle.SingleBorderWindow;
                ResizeMode = _prevResizeMode != ResizeMode.NoResize ? _prevResizeMode : ResizeMode.CanResize;

                if (_handheldLegendBar != null) _handheldLegendBar.Visibility = Visibility.Collapsed;
                if (_rootGrid != null) _rootGrid.Margin = new Thickness(14);

                if (_btnHandheldToggle != null)
                {
                    _btnHandheldToggle.Content = "🎮 Handheld";
                    _btnHandheldToggle.Background = BgCardHover;
                    _btnHandheldToggle.BorderBrush = BorderColor;
                }

                ShowToast("🎮 Handheld Mode: OFF (Standard Desktop Window)");
            }
        }

        private Border BuildHandheldLegendBar()
        {
            var bar = new Border
            {
                Background = new SolidColorBrush(Color.FromArgb(235, 12, 16, 23)),
                BorderBrush = BorderStrong,
                BorderThickness = new Thickness(0, 1, 0, 0),
                Height = 44,
                VerticalAlignment = VerticalAlignment.Bottom,
                HorizontalAlignment = HorizontalAlignment.Stretch,
                Visibility = Visibility.Collapsed,
                Padding = new Thickness(16, 0, 16, 0)
            };

            var stack = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center
            };

            stack.Children.Add(CreateLegendItem("A", Color.FromRgb(46, 204, 113), "Select / Install"));
            stack.Children.Add(CreateLegendItem("B", Color.FromRgb(231, 76, 60), "Back / Close"));
            stack.Children.Add(CreateLegendItem("X", Color.FromRgb(52, 152, 219), "Search"));
            stack.Children.Add(CreateLegendItem("Y", Color.FromRgb(241, 196, 15), "Toggle View"));
            stack.Children.Add(CreateLegendItem("LB/RB", Color.FromRgb(149, 165, 166), "Tabs"));
            stack.Children.Add(CreateLegendItem("LT/RT", Color.FromRgb(149, 165, 166), "Filters"));
            stack.Children.Add(CreateLegendItem("View", Color.FromRgb(155, 89, 182), "Exit Handheld (F11)"));

            bar.Child = stack;
            return bar;
        }

        private FrameworkElement CreateLegendItem(string buttonText, Color badgeColor, string actionText)
        {
            var panel = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(10, 0, 10, 0)
            };

            var badge = new Border
            {
                Background = new SolidColorBrush(badgeColor),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(7, 2, 7, 2),
                Margin = new Thickness(0, 0, 6, 0),
                VerticalAlignment = VerticalAlignment.Center
            };
            var txtBadge = new TextBlock
            {
                Text = buttonText,
                FontSize = 11,
                FontWeight = FontWeights.Bold,
                Foreground = Brushes.Black,
                HorizontalAlignment = HorizontalAlignment.Center
            };
            badge.Child = txtBadge;

            var txtLabel = new TextBlock
            {
                Text = actionText,
                FontSize = 12,
                Foreground = TextMuted,
                VerticalAlignment = VerticalAlignment.Center
            };

            panel.Children.Add(badge);
            panel.Children.Add(txtLabel);
            return panel;
        }

        private void StartGamepadPolling()
        {
            if (_gamepadTimer != null) return;
            _gamepadTimer = new DispatcherTimer(DispatcherPriority.Input);
            _gamepadTimer.Interval = TimeSpan.FromMilliseconds(32);
            _gamepadTimer.Tick += GamepadTimer_Tick;
            _gamepadTimer.Start();
        }

        private void GamepadTimer_Tick(object sender, EventArgs e)
        {
            if (!XInputNative.IsAvailable) return;
            XINPUT_STATE state = new XINPUT_STATE();
            if (XInputNative.GetState(0, ref state) != 0)
            {
                _prevGamepadButtons = 0;
                _prevLeftTrigger = 0;
                _prevRightTrigger = 0;
                return;
            }

            ushort buttons = state.Gamepad.wButtons;
            ushort pressed = (ushort)(buttons & ~_prevGamepadButtons);
            byte lt = state.Gamepad.bLeftTrigger;
            byte rt = state.Gamepad.bRightTrigger;
            short stickX = state.Gamepad.sThumbLX;
            short stickY = state.Gamepad.sThumbLY;

            const short deadzone = 16000;
            const byte trigThreshold = 120;

            // View / Back button toggles Handheld Mode
            if ((pressed & XInputButtons.BACK) != 0)
            {
                ToggleHandheldMode();
            }
            // Start / Menu button refreshes games library
            else if ((pressed & XInputButtons.START) != 0)
            {
                RefreshGames();
                ShowToast("↻ Library rescanned");
            }
            // LB / RB: Cycle main navigation tabs
            else if ((pressed & XInputButtons.LEFT_SHOULDER) != 0)
            {
                CycleTabs(-1);
            }
            else if ((pressed & XInputButtons.RIGHT_SHOULDER) != 0)
            {
                CycleTabs(1);
            }
            // Y: Toggle Grid / List view
            else if ((pressed & XInputButtons.Y) != 0)
            {
                _isGridView = !_isGridView;
                _gamesScrollViewer.Visibility = _isGridView ? Visibility.Visible : Visibility.Collapsed;
                _listGamesView.Visibility = _isGridView ? Visibility.Collapsed : Visibility.Visible;
                if (_isGridView) UpdateGamepadFocus(_focusedGameIndex);
                ShowToast(_isGridView ? "🔲 Grid View" : "☰ List View");
            }
            // X: Focus Search Input
            else if ((pressed & XInputButtons.X) != 0)
            {
                if (_currentTab != "games") SwitchTab("games");
                if (_txtSearch != null)
                {
                    _txtSearch.Focus();
                    _txtSearch.SelectAll();
                }
            }

            // LT / RT: Cycle Quick Filters
            if (lt > trigThreshold && _prevLeftTrigger <= trigThreshold)
            {
                CycleFilters(-1);
            }
            else if (rt > trigThreshold && _prevRightTrigger <= trigThreshold)
            {
                CycleFilters(1);
            }

            // A: Select / Install / Open Drawer
            if ((pressed & XInputButtons.A) != 0)
            {
                if (_drawerPanel != null && _drawerPanel.Visibility == Visibility.Visible)
                {
                    OnInstallClicked();
                }
                else if (_currentTab == "games" && _focusedGameIndex >= 0 && _focusedGameIndex < _currentRenderedGames.Count)
                {
                    OpenDrawer(_currentRenderedGames[_focusedGameIndex]);
                }
            }
            // B: Back / Close Drawer / Clear Search
            else if ((pressed & XInputButtons.B) != 0)
            {
                if (_drawerPanel != null && _drawerPanel.Visibility == Visibility.Visible)
                {
                    CloseDrawer();
                }
                else if (_txtSearch != null && !string.IsNullOrEmpty(_txtSearch.Text))
                {
                    _txtSearch.Text = "";
                    Focus();
                }
            }

            // Directional Navigation (D-pad & Left Stick)
            int dir = 0;
            if ((buttons & XInputButtons.DPAD_UP) != 0 || stickY > deadzone) dir = 1;
            else if ((buttons & XInputButtons.DPAD_DOWN) != 0 || stickY < -deadzone) dir = 2;
            else if ((buttons & XInputButtons.DPAD_LEFT) != 0 || stickX < -deadzone) dir = 3;
            else if ((buttons & XInputButtons.DPAD_RIGHT) != 0 || stickX > deadzone) dir = 4;

            if (dir != 0)
            {
                bool shouldAct = false;
                if (dir != _lastNavDirection)
                {
                    _lastNavDirection = dir;
                    _gamepadNavHoldCount = 0;
                    shouldAct = true;
                }
                else
                {
                    _gamepadNavHoldCount++;
                    // Initial repeat delay (~350ms / 11 ticks), then repeat every ~120ms (4 ticks)
                    if (_gamepadNavHoldCount > 11 && (_gamepadNavHoldCount % 4 == 0))
                    {
                        shouldAct = true;
                    }
                }

                if (shouldAct)
                {
                    HandleDirectionalNav(dir);
                }
            }
            else
            {
                _lastNavDirection = 0;
                _gamepadNavHoldCount = 0;
            }

            _prevGamepadButtons = buttons;
            _prevLeftTrigger = lt;
            _prevRightTrigger = rt;
        }

        private void HandleDirectionalNav(int dir)
        {
            if (_drawerPanel != null && _drawerPanel.Visibility == Visibility.Visible)
            {
                if (dir == 3) // Left
                {
                    if (_currentDrawerTab == "logs") SwitchDrawerTab("ini");
                    else if (_currentDrawerTab == "ini") SwitchDrawerTab("guide");
                }
                else if (dir == 4) // Right
                {
                    if (_currentDrawerTab == "guide") SwitchDrawerTab("ini");
                    else if (_currentDrawerTab == "ini") SwitchDrawerTab("logs");
                }
                return;
            }

            if (_currentTab != "games" || _currentRenderedGames == null || _currentRenderedGames.Count == 0) return;

            int cols = 1;
            if (_isGridView && _gridWrapPanel != null && _gridWrapPanel.ActualWidth > 0)
            {
                cols = Math.Max(1, (int)(_gridWrapPanel.ActualWidth / 222));
            }

            int cur = _focusedGameIndex;
            if (cur < 0) cur = 0;

            int next = cur;
            if (dir == 1) // Up
            {
                next = _isGridView ? cur - cols : cur - 1;
            }
            else if (dir == 2) // Down
            {
                next = _isGridView ? cur + cols : cur + 1;
            }
            else if (dir == 3) // Left
            {
                next = cur - 1;
            }
            else if (dir == 4) // Right
            {
                next = cur + 1;
            }

            if (next < 0) next = 0;
            if (next >= _currentRenderedGames.Count) next = _currentRenderedGames.Count - 1;

            UpdateGamepadFocus(next);
        }

        private void UpdateGamepadFocus(int newIndex)
        {
            if (_currentRenderedGames == null || _currentRenderedGames.Count == 0)
            {
                _focusedGameIndex = -1;
                return;
            }

            if (newIndex < 0) newIndex = 0;
            if (newIndex >= _currentRenderedGames.Count) newIndex = _currentRenderedGames.Count - 1;
            _focusedGameIndex = newIndex;

            if (_isGridView)
            {
                for (int i = 0; i < _gridWrapPanel.Children.Count; i++)
                {
                    var card = _gridWrapPanel.Children[i] as Border;
                    if (card == null) continue;
                    var g = card.Tag as GameInfo;
                    if (i == _focusedGameIndex)
                    {
                        card.BorderBrush = AccentEmeraldStrong;
                        card.BorderThickness = new Thickness(3.5);
                        var glow = new DropShadowEffect
                        {
                            Color = Color.FromRgb(241, 196, 15),
                            BlurRadius = 24,
                            ShadowDepth = 0,
                            Opacity = 0.85
                        };
                        card.Effect = glow;
                        card.BringIntoView();
                    }
                    else
                    {
                        card.BorderBrush = (g != null && g.Installed) ? AccentEmerald : BorderColor;
                        card.BorderThickness = new Thickness((g != null && g.Installed) ? 2 : 1);
                        card.Effect = new DropShadowEffect
                        {
                            Color = Colors.Black,
                            BlurRadius = 16,
                            ShadowDepth = 5,
                            Opacity = _isLightTheme ? 0.12 : 0.48
                        };
                    }
                }
            }
            else
            {
                if (_listGamesView != null)
                {
                    _listGamesView.SelectedIndex = _focusedGameIndex;
                    if (_listGamesView.SelectedItem != null)
                    {
                        _listGamesView.ScrollIntoView(_listGamesView.SelectedItem);
                    }
                }
            }
        }

        private static readonly string[] NavTabs = new string[] { "games", "core", "myfsr", "settings", "about" };

        private void CycleTabs(int delta)
        {
            int idx = Array.IndexOf(NavTabs, _currentTab);
            if (idx < 0) idx = 0;
            int next = idx + delta;
            if (next < 0) next = NavTabs.Length - 1;
            if (next >= NavTabs.Length) next = 0;
            SwitchTab(NavTabs[next]);
        }

        private static readonly string[] QuickFilterKeys = new string[] { "all", "installed", "uninstalled", "optiscaler", "direct", "reengine" };

        private void CycleFilters(int delta)
        {
            int idx = Array.IndexOf(QuickFilterKeys, _quickFilter);
            if (idx < 0) idx = 0;
            int next = idx + delta;
            if (next < 0) next = QuickFilterKeys.Length - 1;
            if (next >= QuickFilterKeys.Length) next = 0;
            string target = QuickFilterKeys[next];

            _quickFilter = target;
            UpdateFilterPillVisuals();
            FilterGames();
            ShowToast("Filter: " + target);
        }
        #endregion
    }
}
