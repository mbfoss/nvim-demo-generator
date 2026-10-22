# nvim-demo-tool

Script a Neovim session, record it through a pseudoterminal, and render the
result as a GIF. Built for plugin README demos: deterministic sizes and fonts,
readable typing speeds, captions in the tabline, an optional screenkey-style
keystroke ticker, and screen-aware waits instead of guessed delays.

- **Record**: Neovim runs in a PTY at a fixed size; keystrokes are fed in from a
  scene file and the terminal output is written as an asciinema v2 `.cast`.
- **Render**: [agg](https://github.com/asciinema/agg) turns the cast into a GIF.
- **Wait**: `wait`/`wait-no` steps parse the rendered screen with
  [pyte](https://github.com/selectel/pyte), so scenes wait for the UI to catch
  up rather than sleeping a fixed amount.

Python 3.9+ and no third-party Python packages beyond pyte (used only for
`wait` steps). Neovim, agg, and a monospace font are the external requirements.

## Install

```sh
git clone <this-repo> ~/src/nvim-demo-tool
ln -s ~/src/nvim-demo-tool/bin/nvim-demo ~/.local/bin/nvim-demo
```

`brew install agg` and `pip install pyte` (or your package manager) cover the
rest. Check a machine with:

```sh
nvim-demo check scene.scene
```

## Quick start

`examples/hello.scene`:

```
size 80x22
init init.lua
out out/hello.gif

keycast on
caption nvim-demo  ·  a scripted Neovim session
sleep 400ms
key i
type hello from nvim-demo
key <Esc>
sleep 600ms
wait hello from nvim-demo
```

`examples/init.lua` is a minimal vimrc that calls the tabline helper:

```lua
require("nvim_demo").setup()
```

Record and render:

```sh
nvim-demo record examples/hello.scene
```

The cast and GIF are written next to the scene (or wherever `out`/`cast`
point). `--no-render` stops after the cast; `--cols`/`--rows` override the
size; `-v` prints the agg command.

Neovim is launched as `nvim --clean -u <init>`. The tool prepends its own root
to `'runtimepath'` and sets `$NVIM_DEMO_TOOL`, so a scene's init can extend the
path and use the caption helper without depending on the user's config:

```lua
local demo = vim.fn.fnamemodify(debug.getinfo(1, "S").source:sub(2), ":p:h")
vim.opt.rtp:append(demo .. "/..") -- the plugin being demonstrated
vim.opt.rtp:append(demo)          -- scene-local colors/, etc.
```

## Scene language

One action per line. Blank lines and lines starting with `#` are ignored. Paths
are relative to the scene file's directory; `~` and environment variables are
expanded.

### Directives

| Directive | Meaning |
| --- | --- |
| `size COLSxROWS` | Terminal size. Default `100x33`, which leaves room for a tabline, statusline and command line. |
| `nvim PATH` | Neovim binary. Default `$NVIM`, else `nvim`. |
| `init PATH` | vimrc passed with `-u`. |
| `rtp PATH` | Extra `'runtimepath'` entry (repeatable). |
| `cwd PATH` | Working directory. Defaults to the scene's directory. |
| `out PATH` | Output GIF. Defaults to the scene path with `.gif`. |
| `cast PATH` | Kept cast. Defaults to the output path with `.cast`. |
| `env NAME=VALUE` | Environment entry (repeatable). |
| `typespeed DURATION` | Pause after each typed character. Default `45ms`. |
| `keyspeed DURATION` | Pause after each key token. Default `30ms`. |
| `settle DURATION` | Quiet period that marks startup done. Default `150ms`. |
| `wait-timeout DURATION` | Default timeout for `wait`/`wait-no`. Default `5s`. |
| `hold DURATION` | Extra final hold before Neovim is shut down. Default `1s`. |
| `keycast on\|off` | Show typed keys in a ticker above the statusline. Default `off`. |
| `keycast-width N` | Fixed ticker width in cells. Default `15`. |

Durations accept `250ms`, `1.5s`, `2m`, or a bare number of seconds.

### Render directives

Passed to agg. agg's defaults apply when omitted, except `renderer`, which
defaults to `resvg` (agg's own default is `swash`). The `swash` backend leaves
notches where rounded box-drawing corners (`╭╮╰╯`, as used by Nvim's
`border = "rounded"` floats) meet the straight border segments; `resvg` draws
them cleanly. Set `renderer swash` to opt back in.

| Directive | agg option |
| --- | --- |
| `font-family NAME` | `--font-family` |
| `font-dir PATH` | `--font-dir` (repeatable) |
| `font-size PX` | `--font-size` (integer) |
| `line-height RATIO` | `--line-height` (>= 1.0) |
| `theme NAME` | `--theme` (`nord`, `dracula`, `github-dark`, ...) |
| `renderer BACKEND` | `--renderer` (`resvg` by default; `swash` is agg's default) |
| `fps N` | `--fps-cap` |
| `idle-time-limit SEC` | `--idle-time-limit` |
| `last-frame-duration SEC` | `--last-frame-duration` |
| `speed FACTOR` | `--speed` |

A 100x33 recording at font size 17 and line-height 1.19 renders to 1040x688.

### Steps

| Step | Effect |
| --- | --- |
| `caption TEXT` | Put TEXT in the tabline (see the Lua helper below). |
| `type TEXT` | Type TEXT one character at a time. `\n`/`\r` become Enter, `\t` a Tab, `\\` a backslash. |
| `key KEYS` | Send Vim key notation: `key <C-f>`, `key <Esc>:w<CR>`. |
| `sleep DURATION` | Wait while output keeps being captured. |
| `wait REGEX` | Wait until the Python regex matches the rendered screen. |
| `wait-no REGEX` | Wait until the regex matches nothing on screen. |
| `sh COMMAND` | Run a shell command in `cwd` between steps. |

`wait` is the reliable way to synchronise: wait for the picker title, a result
filename, or the statusline path. Python regex syntax applies (`\.` for a
literal dot), not Lua patterns.

Key notation covers the usual suspects: `<CR>`, `<Esc>`, `<Tab>`, `<BS>`,
`<Space>`, arrows, Home/End, Delete/Insert, PageUp/PageDown, F1-F12,
`<C-a>`-`<C-z>` and their punctuation forms, and `<M-x>`. Literal text can be
mixed in, so `key :qa!<CR>` works. Use `<lt>` for a literal `<`.

## Captions in the tabline

`lua/nvim_demo.lua` is on the tool's runtimepath. Call `setup()` from the scene
init once:

```lua
require("nvim_demo").setup({
  fg = "#2e2f33",   -- caption text; derived from Normal's background by default
  bg = "#90b8e3",   -- caption bar; derived from Function's foreground by default
  fill = "#3a3b41", -- rest of the tabline; derived from TabLineFill by default
})
```

The recorder sets the text with an RPC call to `caption()`, so `caption` steps
work while the user is mid-command-line or in insert mode. Calling `caption()`
directly is enough if you want to render the text yourself:

```lua
require("nvim_demo").caption("Anything")
```

## Keystroke ticker

`keycast on` shows what is being typed in a small bordered float above the
statusline, using the editor's `Normal` background (not `NormalFloat`'s
near-black) and a non-bold title. Characters from
`type` steps appear literally; `key` tokens
appear in their Vim notation, so a step like `key <C-f>` or `key :w<CR>`
displays `<C-f>` or `:w<CR>`. The ticker keeps the most recent
`keycast-width` cells in a fixed-width box with centred text, dropping older
keys off the left as typing continues.

```
size 80x22
init init.lua
keycast on
keycast-width 40
...
key i
type hello from nvim-demo
key <Esc>
```

The recorder refreshes the ticker through an RPC call after every character,
so `keycast on` adds mild per-keystroke latency (roughly one `nvim
--server --remote-expr` invocation). It does not require `setup()`.

## How it works

1. Spawn Neovim in a PTY of the requested size with `--listen` for RPC.
2. Wait until startup output has been quiet for `settle`.
3. Start the cast from a cleared screen and force a full redraw with `CTRL-L`,
   so the GIF never opens on a blank or half-drawn frame.
4. Execute the steps, feeding output to both the cast writer and a pyte screen.
5. Write the cast, terminate Neovim, and call agg with the scene's render
   settings.

`record` keeps the `.cast` next to the GIF, which is handy when a render looks
wrong but the recording is fine.

## Tests

```sh
python3 -m unittest discover -s tests
```

The unit tests cover key encoding, scene parsing, and the SGR normalization
pyte needs; they do not launch Neovim.
