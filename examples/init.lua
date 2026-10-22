-- Minimal init for the example scene. `nvim-demo` prepends its own root to
-- 'runtimepath', so `require("nvim_demo")` works before this file runs.
vim.o.number = true
vim.o.termguicolors = true
vim.o.swapfile = false
vim.o.shadafile = "NONE"
vim.o.shortmess = vim.o.shortmess .. "I"

require("nvim_demo").setup()
