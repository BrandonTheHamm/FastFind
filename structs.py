#!/usr/bin/env python
import json

#------------------------------------------------------------------------------
class FastFindResult:
	def __init__(self, filename: str, line_number: int, startpos: int, matchlen: int):
		self.filename = filename
		self.line_number = line_number
		self.start_char_index = startpos
		self.match_length = matchlen

	@staticmethod
	def from_json(json_content) -> FastFindResult:
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



