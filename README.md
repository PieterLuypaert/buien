# buien

Should I cycle now? `buien` shows the rain for the next three hours as a small chart in your terminal, with a summary such as "dry until 14:20, then 15 min of light rain". The data comes from Buienradar, so it works in the Netherlands, Belgium and the border regions.

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

Run `buien`, or `buien -h` for every option.

## When to leave

`buien --trip 25` tells you when to leave to stay dry on a 25-minute ride, such as "leave between 15:20 and 15:30 to stay dry for 25 min", and draws that dry stretch in green on the chart's time axis. With `--short` it exits with 0 when you can leave right now and with 2 when you cannot, so a script can decide for you:

```sh
buien --trip 20 --short >/dev/null && echo "go now" || echo "wait a bit"
```

## Live view

`buien --live` fills the terminal with the chart and keeps it up to date, with a tab for every saved place:

| Key | Does |
| --- | --- |
| ← → | move through the hours; the line under the chart gives the rain at that moment |
| ↑ ↓ or tab | the previous or next place |
| / | search a place, which opens in a tab of its own |
| s | save the place on screen under a name |
| r | fetch the forecast again, past the cache |
| q or esc | quit |

With `--trip 25` it also says when to leave, for whichever place is on screen.

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
