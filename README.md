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

## Tab completion

buien completes its options and your saved places. Add the line for your shell to its startup file:

```sh
eval "$(buien --completions zsh)"     # ~/.zshrc, after compinit
eval "$(buien --completions bash)"    # ~/.bashrc
buien --completions fish > ~/.config/fish/completions/buien.fish
```
