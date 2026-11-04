namespace Nam2ZoomDesktop;

public sealed record EffectSlot(int Number, uint Id, string Stem, string DefaultName)
{
    public static readonly EffectSlot[] All = [
        new(1, 0x04001787, "N2ZBANK", "N2Z Bank"),
        new(2, 0x04001387, "N2ZBNK2", "N2Z Bnk2"),
        new(3, 0x04001397, "N2ZBNK3", "N2Z Bnk3")
    ];
    public string Filename => Stem + ".ZD2";
    public override string ToString() => $"Slot {Number} · 0x{Id:X8}";
    public static EffectSlot Get(int number) => All.FirstOrDefault(s => s.Number == number)
        ?? throw new InvalidDataException("Choose effect slot 1, 2 or 3.");
}
