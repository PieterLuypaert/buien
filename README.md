# buien

Should I cycle now? `buien` fills your terminal with Buienradar's rain radar, playing the next two hours over a map of the Low Countries with your places on it. Below the map is a chart of the rain at your place for the next three hours, with a summary such as "dry until 14:20, then 15 min of light rain". It works in the Netherlands, Belgium and the border regions.

## Install

With [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/):

```sh
uv tool install git+https://github.com/PieterLuypaert/buien
pipx install git+https://github.com/PieterLuypaert/buien
```

Update with `uv tool upgrade buien` or `pipx upgrade buien`.

Or as one file, since buien needs nothing but `python3` (3.9 or newer):

```sh
mkdir -p ~/.local/bin
curl -fsSL https://raw.githubusercontent.com/PieterLuypaert/buien/main/buien -o ~/.local/bin/buien
chmod +x ~/.local/bin/buien
```

Run `buien`, or `buien -h` for every option. The first time, buien asks where home is.

## When to leave

`buien --trip 25` tells you when to leave to stay dry on a 25-minute ride, such as "leave between 15:20 and 15:30 to stay dry for 25 min", and draws that dry stretch in green on the chart's time axis. With `--short` it exits with 0 when you can leave right now and with 2 when you cannot, so a script can decide for you:

```sh
buien --trip 20 --short >/dev/null && echo "go now" || echo "wait a bit"
```

## The live screen

Plain `buien`, or `buien gent` for somewhere else, opens the live screen with a tab for every saved place. The map plays the radar's next two hours, and the cursor in the chart moves along with it. On a wide terminal the map sits beside the chart, otherwise above it. Everything refreshes by itself: the forecast every minute, the radar every five.

| Key | Does |
| --- | --- |
| ← → or the scroll wheel | pause and move through the hours; the map shows that moment, and the line under the chart gives the rain then |
| space | play the map again |
| ↑ ↓ or tab | the previous or next place |
| / | search a place, which opens in a tab of its own |
| s | save the place on screen under a name |
| r | fetch the forecast and the radar again, past the cache |
| q or esc | quit |

With `--trip 25` it also says when to leave, for whichever place is on screen. In a short terminal the map makes way for the chart. buien takes the scroll wheel, so to select text, hold the modifier your terminal uses for that, such as Option or Shift.

The map is Buienradar's own radar over a map of the area it covers. The radar of now lags the clock by about ten minutes, which the title says, and the frames after it are Buienradar's forecast. The kinds of rain on the map follow Buienradar's colours roughly; the chart has the exact amounts for your place.

`buien --once` prints the map of now and the chart once and gives you the prompt back. Piped into another command, buien prints the chart as plain text.

## Tab completion

buien completes its options and your saved places. Add the line for your shell to its startup file:

```sh
eval "$(buien --completions zsh)"     # ~/.zshrc, after compinit
eval "$(buien --completions bash)"    # ~/.bashrc
buien --completions fish > ~/.config/fish/completions/buien.fish
```

## In a status bar or a script

`buien --short` prints only the summary and `buien --json` the whole forecast. A forecast is reused for five minutes, so a status bar may run buien as often as it likes. In tmux, for example:

```tmux
set -g status-right '#(buien --short)'
```
