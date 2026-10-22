--- Tabline captions and a keystroke ticker for nvim-demo recordings.
---
--- The recorder sets a caption with an RPC call to `caption()` and the keys it
--- has typed with `keys()`. Calling `setup()` installs a tabline that renders
--- the caption as a centered bar, in the style the demo GIFs use. Keep the
--- module on 'runtimepath' (the recorder prepends its own root, and
--- `$NVIM_DEMO_TOOL` is set to that root).
local M = {}

local HL_CAPTION     = "NvimDemoCaption"
local HL_FILL        = "NvimDemoTabLineFill"
local HL_KEY_BORDER  = "NvimDemoFloatBorder"
local HL_KEY_TITLE   = "NvimDemoFloatTitle"

local key_buf = nil
local key_win = nil
local key_hl_ready = false

local function hex(value)
	if type(value) == "number" then
		return string.format("#%06x", value)
	end
	return nil
end

local function group(name)
	local ok, hl = pcall(vim.api.nvim_get_hl, 0, { name = name, link = false })
	return ok and hl or {}
end

--- Set the text shown by the tabline. An empty string or nil clears it.
---@param text string?
---@return string
function M.caption(text)
	vim.g.nvim_demo_caption = text or ""
	vim.cmd("redrawtabline")
	return ""
end

local function keys_close()
	if key_win and vim.api.nvim_win_is_valid(key_win) then
		vim.api.nvim_win_close(key_win, true)
	end
	key_win = nil
end

-- The ticker uses the editor's Normal background rather than NormalFloat's
-- near-black, and a title that keeps FloatTitle's colour without the bold.
-- The border gets the same background so the frame does not read as a darker
-- slab around the text.
local function ensure_key_hl()
	if key_hl_ready then
		return
	end
	local normal = group("Normal")
	local border = group("FloatBorder")
	local title  = group("FloatTitle")
	vim.api.nvim_set_hl(0, HL_KEY_BORDER, {
		fg = border.fg or normal.fg,
		bg = normal.bg,
	})
	vim.api.nvim_set_hl(0, HL_KEY_TITLE, {
		fg = title.fg or normal.fg,
		bg = normal.bg,
		bold = false,
	})
	key_hl_ready = true
end

--- Show the keys typed so far in a one-line ticker above the statusline.
--- An empty string or nil hides it.
---@param text string?
---@return string
function M.keys(text)
	text = text or ""
	if text == "" then
		keys_close()
		return ""
	end

	if not (key_buf and vim.api.nvim_buf_is_valid(key_buf)) then
		key_buf = vim.api.nvim_create_buf(false, true)
	end
	vim.api.nvim_buf_set_lines(key_buf, 0, -1, false, { " " .. text .. " " })

	ensure_key_hl()

	-- A regular bordered float in Normal's colours, bottom-right above the
	-- statusline (or the last content row when there is none).
	local has_status = vim.o.laststatus == 2
		or (vim.o.laststatus == 1 and #vim.api.nvim_tabpage_list_wins(0) > 1)
	local config = {
		relative  = "editor",
		anchor    = "SE",
		row       = vim.o.lines - (has_status and 3 or 2),
		col       = vim.o.columns - 2,
		width     = math.max(1, math.min(vim.fn.strdisplaywidth(text) + 2, vim.o.columns - 8)),
		height    = 1,
		border    = "rounded",
		title     = { { " keys ", HL_KEY_TITLE } },
		style     = "minimal",
		focusable = false,
		noautocmd = true,
		zindex    = 250,
	}

	if key_win and vim.api.nvim_win_is_valid(key_win) then
		vim.api.nvim_win_set_config(key_win, config)
	else
		key_win = vim.api.nvim_open_win(key_buf, false, config)
		vim.wo[key_win].wrap = false
		vim.wo[key_win].winhl =
			"Normal:Normal,FloatBorder:" .. HL_KEY_BORDER .. ",FloatTitle:" .. HL_KEY_TITLE
	end
	return ""
end

--- The tabline expression. Text is centred; the rest of the row uses the fill
--- highlight, so the bar reads as one segment of colour rather than a full row.
---@return string
function M.tabline()
	local text = vim.g.nvim_demo_caption or ""
	local fill = "%#" .. HL_FILL .. "#"
	if text == "" then
		return fill .. "%="
	end

	local label = " " .. text:gsub("%%", "%%%%") .. " "
	local label_width = vim.fn.strdisplaywidth(label)
	local columns = vim.o.columns
	local left = math.max(0, math.floor((columns - label_width) / 2))
	local right = math.max(0, columns - label_width - left)

	return fill
		.. string.rep(" ", left)
		.. "%#" .. HL_CAPTION .. "#" .. label
		.. fill
		.. string.rep(" ", right)
end

--- Install the centred-caption tabline.
---@param opts table? `fg`, `bg`, `bold`, `fill` override the derived colours.
function M.setup(opts)
	opts = opts or {}

	local normal = group("Normal")
	local accent = group("Function")
	local fill   = group("TabLineFill")

	local fg   = opts.fg or hex(normal.bg) or "#000000"
	local bg   = opts.bg or hex(accent.fg) or "#90b8e3"
	local bar  = opts.fill or hex(fill.bg) or hex(normal.bg) or "#3a3b41"
	local bold = opts.bold
	if bold == nil then bold = true end

	vim.api.nvim_set_hl(0, HL_CAPTION, { fg = fg, bg = bg, bold = bold })
	vim.api.nvim_set_hl(0, HL_FILL, { fg = hex(normal.fg) or fg, bg = bar })

	vim.g.nvim_demo_caption = vim.g.nvim_demo_caption or ""
	vim.o.showtabline = 2
	vim.o.tabline = "%!v:lua.require'nvim_demo'.tabline()"
end

return M
