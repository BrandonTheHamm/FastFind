#!/usr/bin/env python

#------------------------------------------------------------------------------
class ResultLocation:
	def __init__(self, filename: str, line_number: int, charpos: int):
		self.filename = filename
		self.line_number = line_number
		self.charpos = charpos
