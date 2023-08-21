import sublime, sublime_plugin
import os
import subprocess
# import string
import threading
import errno
import json
from .typing import List, Optional

#------------------------------------------------------------------------------
FASTFIND_PLUGIN_DIR = os.path.basename(os.path.dirname(os.path.realpath(__file__)))

# Package Control on ST3 compresses the package into a single "package-name.sublime-package" file,
# but ST3 internally treats the location of the package's contents as being in "Packages/packages-name/"
if FASTFIND_PLUGIN_DIR.find(".sublime-package") != -1:
	FASTFIND_PLUGIN_DIR = FASTFIND_PLUGIN_DIR[0:FASTFIND_PLUGIN_DIR.find(".sublime-package")]

FASTFIND_CONTEXT_MENU = os.path.dirname(os.path.realpath(__file__)) + "/Context.sublime-menu"
FASTFIND_SETTINGS_FILE = os.path.dirname(os.path.realpath(__file__)) + "/fastfind.sublime-settings"
FASTFIND_SYNTAX_FILE = "Packages/" + FASTFIND_PLUGIN_DIR + "/FastFindResults.hidden-tmLanguage"

#------------------------------------------------------------------------------
def get_setting(key, default=None, view=None):
		s = sublime.load_settings("fastfind.sublime-settings")
		if view == None:
			view = sublime.active_window().active_view()

		if s.has("FastFindSublime_%s" % key):
			return s.get("FastFindSublime_%s" % key)
		else:
			error_string = ('\"{0}\" settting not specified\n'
			'Add the following to your user FastFind.sublime-setttings:\n\n'
			'"FastFindSublime_file_type_pattern":\n'
			'["c", "h", "sh", "make"],\n'
			'"FastFindSublime_non_std_file_type_pattern":\n'
			'["x", "s", "scons", "api","],\n'
			'"FastFindSublime_ignore_folders": [],\n'
			'"FastFindSublime_prompt_before_searching": false,\n'
			'"FastFindSublime_executable": "rg",\n'
			'"FastFindSublime_executable": "rg",\n'
			'"FastFindSublime_before_context":1,\n'
			'"FastFindSublime_after_context":1,\n'
			'"FastFindSublime_display_outline": true,'.format(key))
			sublime.error_message(error_string)


#------------------------------------------------------------------------------
class FastFindResult:
	def __init__(self, filename: str, line_number: int, startpos: int, matchlen: int):
		self.filename = filename
		self.line_number = line_number
		self.start_char_index = startpos
		self.match_length = matchlen

	@staticmethod
	def from_json(json_content):
		start_pos = int(json_content['submatches'][0]['start'])
		match_len = int(json_content['submatches'][0]['end']) - start_pos + 1
		return FastFindResult(json_content['path']['text'],
			int(json_content['line_number']),
			start_pos,
			match_len)

	def to_string(self) -> str:
		return "FastFindResult: filename = {0}\n\tline_number = {1}\n\tstart_char_index = {2}\n\tmatch_length = {3}\n".format(
			self.filename,
			self.line_number,
			self.start_char_index,
			self.match_length)


#------------------------------------------------------------------------------
class FastFindSublimeWorker(threading.Thread):
	def __init__(self, view, platform, root, symbol, folder, executable):
		super(FastFindSublimeWorker, self).__init__()
		self._view = view
		self._platform = platform
		self._root = root
		self._symbol = symbol
		self._folder = folder
		self._executable = executable
		self._output = []

	def make_fastfind_cmd(self, folder, word):
		#FIXME(BH): replace with search executable specified in user preferences
		fastfind_arg_list = ["rg"]
		fastfind_arg_list.append("--json")

		fastfind_arg_list.append("-B"+str(get_setting("before_context")))
		fastfind_arg_list.append("-A"+str(get_setting("after_context")))

		std_file_types = get_setting("file_type_pattern")
		if std_file_types is not None:
			for file_type in std_file_types:
				fastfind_arg_list.append("-t"+file_type)

		non_std_file_types = get_setting("non_std_file_type_pattern")
		if non_std_file_types is not None:
			for file_type in non_std_file_types:
				fastfind_arg_list.append("--type-add")
				fastfind_arg_list.append("%s:*.%s" % (file_type, file_type))
			for file_type in non_std_file_types:
				fastfind_arg_list.append("-t"+file_type)

		# search path defaults to the directory of currently opened file
		# if a project is loaded, then use that project's directory as the search path
		# if a folder is specified, append the folder name to the search path
		
		current_filename = self._view.file_name()
		if current_filename is None or current_filename == "":
			sublime.error_message("No open document! What are you trying to find???")
			return None, None

		cwd = os.path.dirname(current_filename)
		# print("FastFind: Current File Directory = {0}".format(cwd))
		path = cwd

		# check to see if a project is currently loaded
		project_filename = self._view.window().project_file_name()
		if project_filename is not None and project_filename != "":
			# use this project's directory as the base search path
			path = os.path.dirname(self._view.window().project_file_name())
		# 	print("FastFind: Using project directory: {0}".format(path))
		# else:
		# 	print("FastFind: No project currently loaded")

		if folder != "":
			path = os.path.join(path, folder)

		print("FastFind: Search path is '{0}'".format(path))

		fastfind_arg_list.append("--column")
		fastfind_arg_list.append(word)
		fastfind_arg_list.append(path)

		# print("FastFind: make_fastfind_cmd: fastfind_arg_list = {0}".format(fastfind_arg_list))
		popen_arg_list = {
			"shell": False,
			"stdout": subprocess.PIPE,
			"stderr": subprocess.PIPE,
			"cwd": self._root
		}

		if self._platform == "windows":
			popen_arg_list["creationflags"] = 0x08000000

		return fastfind_arg_list, popen_arg_list

	def run_fastfind(self, folder: str, word: str) -> str:
		fastfind_arg_list, popen_arg_list = self.make_fastfind_cmd(folder, word)
		try:
			proc = subprocess.Popen(fastfind_arg_list, **popen_arg_list)
		except OSError as e:
			if e.errno == errno.ENOENT:
				sublime.error_message("FastFind ERROR: fastfind binary \"%s\" not found!" % self._executable)
			else:
				sublime.error_message("FastFind ERROR: %s failed!" % fastfind_arg_list)
			print("FastFind: Exiting due to error")
			return ""

		output, erroroutput = proc.communicate()

		if erroroutput is not None and erroroutput.strip() != "":
			print("FastFind: erroroutput = '{0}'".format(erroroutput))

		try:
			output = str(output, encoding="utf8")
		except TypeError:
			output = unicode(str(output), encoding="utf8")

		# print("FastFind: output = {0}".format(output))
		return output

	def process_results(self, results):
		for line in results:
			print(line)

	def run(self) -> None:
			results = self.run_fastfind(self._folder, self._symbol)
			search_result_locations = parse_search_results_from_json(results)
			self._output = search_result_locations

#------------------------------------------------------------------------------
def parse_search_results_from_json(content: str) -> List[FastFindResult]:
	results = []
	# NOTE(BH): Ripgrep splits json results using Unix line-endings, so even on Windows,
	# we need split the results on the Unix line termination character and not use os.linesep
	for line in content.split("\n"):
		# print("\n\nline:\n\n{0}\n\n".format(line))
		line = line.strip()
		if line == "":
			# print("blank line...skipping")
			continue
		json_result = json.loads(line)
		# print("json_result: ", json_result)

		if json_result['type'] == 'match':
			# print("found match type")
			find_result = FastFindResult.from_json(json_result['data'])
			if find_result != None:
				# print(find_result.to_string())
				results.append(find_result)
	return results
	

#------------------------------------------------------------------------------
class FastFindCommand(sublime_plugin.TextCommand):
	fastfind_output_info  = {}

	def __init__(self, view: sublime.View):
		self.view = view
		self._executable = None
		self._root = None
		self._find_results = []
		self._current_position = None
		self._saved_viewport_pos = None
		print("FastFind: Plugin Loaded")

	def _update_status(self, workers: List[FastFindSublimeWorker], msgStr: str, show_results: bool, count: int = 0, dir: int = 1) -> None:
		count = count + dir
		found = False

		for worker in workers:
			if worker.is_alive():
				found = True
				if count == 7:
					dir = -1
				elif count == 0:
					dir = 1
				sublime.set_timeout(lambda: self._update_status(workers, msgStr, show_results, count, dir), 100)
				break

		if not found:
			self.view.erase_status("FastFindSublime")
			output = ""
			if show_results:
				for worker in workers:
					for result in worker._output:
						self._find_results.append(result)
					self._display_results_in_jump_list(worker._symbol, worker._output)

	def _select_entry(self, index: int) -> None:
		# print("_select_entry called with index = {0}".format(index))
		if index < 0:
			# return
			print("FastFind: cancelled navigation - return to previous position")
			# cancelled, return to saved position
			self.view.window().focus_view(self.view)
			self.view.sel().clear()
			self.view.sel().add(self._current_position)
			self.view.set_viewport_position(self._saved_viewport_pos, animate=True)
		else:
			# print("skipping...for index = {0}".format(index))
			selected_entry = self._find_results[index]
			# print("_select_entry %d: %s:%d:%d" % (index, selected_entry.filename, selected_entry.line_number, selected_entry.start_char_index))
			view = self._open_basic_file(selected_entry.filename,
				selected_entry.line_number,
				selected_entry.start_char_index,
				False)
			self.view.window().focus_view(view)
		

	def _highlight_entry(self, index: int) -> None:
		# print("_highlight_entry called with index = {0}".format(index))
		highlighted_result = self._find_results[index]
		# print("_highlight_entry %d : %s:%d:%d" % (index, highlighted_result.filename, highlighted_result.line_number, highlighted_result.start_char_index))
		preview = self._open_basic_file(highlighted_result.filename, 
			highlighted_result.line_number,
			highlighted_result.start_char_index,
			True)
		result_location = preview.text_point(highlighted_result.line_number-1, highlighted_result.start_char_index-1)
		result_region = sublime.Region(result_location, result_location+highlighted_result.match_length)
		preview.sel().clear()
		preview.sel().add(result_region)

	def _display_results_in_jump_list(self, symbol: str, locations: List[FastFindResult]):
		self._find_results = locations
		window = self.view.window()

		items = []
		for location in locations:
			items.append(sublime.QuickPanelItem(
				"{0}:{1}".format(os.path.basename(location.filename), location.line_number),
				annotation="FastFind"))

		# print("_display_results: num items = {0}".format(len(items)))
		window.show_quick_panel(items=items,
			on_select=self._select_entry,
			on_highlight=self._highlight_entry, 
			flags=sublime.KEEP_OPEN_ON_FOCUS_LOST, 
			placeholder="FastFind found {0} occurrences of '{1}'".format(len(items), symbol))

	def _display_results_scratch_window(self, symbol: str, output: str):
		before_context = get_setting("before_context")
		after_context = get_setting("after_context")
		FastFind_view = self.view.window().new_file()
		FastFind_view.set_scratch(True)
		FastFind_view.set_name("FastFind results - " + symbol + " " + self._folder)
		FastFindCommand.fastfind_output_info['view'] = FastFind_view
		FastFindCommand.fastfind_output_info['pos'] = 0
		FastFindCommand.fastfind_output_info['text'] = "%s in %s\n\n%s" %  (symbol, self._folder, output)
		FastFindCommand.fastfind_output_info['symbol'] = symbol
		FastFind_view.run_command("display_fast_find_results")
		FastFind_view.set_syntax_file(FASTFIND_SYNTAX_FILE)
		FastFind_view.set_read_only(True)

	def _open_basic_file(self, 
		filename: str, 
		line_number: int, 
		char_index: int, 
		preview_only: bool) -> sublime.View:
		window = self.view.window()
		flags = sublime.ENCODED_POSITION
		if preview_only:
			flags |= sublime.TRANSIENT
		encoded_filename = "{0}:{1}:{2}".format(filename, line_number, char_index)
		view = window.open_file(fname=encoded_filename,group=-1, flags=flags)
		return view

	def _on_search_confirmed(self, symbol):
		print("FastFind: Searching for symbol '%s'" % symbol)
		worker = FastFindSublimeWorker(
				view = self.view,
				platform = sublime.platform(),
				root = self._root,
				symbol = symbol,
				folder = self._folder,
				executable = self._executable)
		worker.start()
		self.workers.append(worker)
		self._update_status(self.workers, symbol, True)

	def run(self, _, folder):
		self._folder = folder
		self._current_position = self.view.sel()[0]
		self._saved_viewport_pos = self.view.viewport_position()
		self._executable = get_setting("executable")
		
		if self._folder == "":
			openViews = self.view.window().views()
			for view in openViews:
				if view.is_scratch():
					if "FastFind results - " in view.name():
						#found a FastFind tab, close it
						self.view.window().focus_view(view)
						self.view.window().run_command("close_file")
			return
		
		if self._folder == "__new__":
			fast_find_menu = os.path.join(FASTFIND_CONTEXT_MENU)
			if os.path.exists(fast_find_menu):
				self.view.window().open_file(fast_find_menu)
			else:
				sublime.error_message("Context.sublime-menu not found at\n%s" % fast_find_menu)
			return

		if self._folder == "__settings__":
			fast_find_settings = os.path.join(FASTFIND_SETTINGS_FILE)
			if os.path.exists(fast_find_settings):
				self.view.window().open_file(fast_find_settings)
			else:
				sublime.error_message("fastfind.sublime-settings not found at\n%s" % fast_find_settings)
			return

		# Search for the first word that is selected. While Sublime Text uses
		# multiple selections, we only want the first selection since simultaneous
		# multiple fastfind lookups are not supported
		first_selection = self.view.sel()[0]
		one = first_selection.a
		two = first_selection.b

		self.view.sel().add(sublime.Region(one, two))
		self.workers = []

		if one == two: #nothing selected, cursor is just at a word, so select full word
			symbol = self.view.substr(self.view.word(one))
		else: #something is selected, so use the selection
			symbol = self.view.substr(first_selection)

		if get_setting("prompt_before_searching") == True:
			print("FastFind: 'prompt_before_searching' not supported yet")
		else:
			self._on_search_confirmed(symbol)

