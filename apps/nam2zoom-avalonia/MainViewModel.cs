using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using Nam2ZoomDesktop;

namespace Nam2Zoom;

public sealed class MainViewModel : INotifyPropertyChanged
{
    public ObservableCollection<ModelSelection> Models { get; } = [];
    public AppPaths Paths { get; } = new();
    public BackendService Backend { get; }
    public BankService Banks { get; }
    private string log = "";
    private string status = "Ready";
    public string Log { get => log; set { log = value; Changed(); } }
    public string Status { get => status; set { status = value; Changed(); } }
    public MainViewModel() { Backend = new(Paths); Banks = new(Paths, Backend); }
    public event PropertyChangedEventHandler? PropertyChanged;
    private void Changed([CallerMemberName] string? property = null) => PropertyChanged?.Invoke(this, new(property));
}
