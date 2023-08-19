#!/usr/bin/env python
from .typing import  List
from .structs import ResultLocation
import sublime

class LocationPicker:
	def __init__(self,
		view: sublime.View,
		locations: List[ResultLocation],
		placeholder: str = ""):
		self.view = view
		window = view.window()
		if not window:
			raise ValueError("Missing Window!")
		self._window = window
		self._items = locations
		self._highlighted_view = None
		self._window.show_quick_panel(items=[
				sublime.QuickPanelItem(trigger=location.filename, annotation="annotationText", kind="kindText")
				for location in locations
			], 
			on_select=self._select_entry, 
			on_highlight=self._highlight_entry, 
			flags=sublime.KEEP_OPEN_ON_FOCUS_LOST, 
			placeholder=placeholder)

	def _select_entry(self, index: int) -> None:
		print("_select_entry")

	def _highlight_entry(self, index: int) -> None:
		print("_highlight_entry")


