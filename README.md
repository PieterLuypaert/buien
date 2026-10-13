# buien

Should I cycle now? `buien` shows the rain for the next three hours as a small chart in your terminal, with a summary such as "dry until 14:20, then 15 min of light rain". The data comes from Buienradar, so it works in the Netherlands, Belgium and the border regions.

```sh
mkdir -p ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/PieterLuypaert/buien/main/buien -o ~/.local/bin/buien
chmod +x ~/.local/bin/buien
```

Needs only `python3`. Run `buien`, or `buien -h` for every option.
