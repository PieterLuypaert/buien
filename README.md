# buien

Moet ik nu fietsen? `buien` toont de regen voor de komende drie uur als een grafiekje in je terminal, met een samenvatting zoals "droog tot 14:20, dan 15 min lichte regen". De data komt van Buienradar, dus het werkt in Nederland, België en de grensstreek.

```sh
mkdir -p ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/PieterLuypaert/buien/main/buien -o ~/.local/bin/buien
chmod +x ~/.local/bin/buien
```

Heeft enkel `python3` nodig. Typ `buien`, of `buien -h` voor alle opties.
