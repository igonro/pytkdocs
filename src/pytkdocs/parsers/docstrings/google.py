"""This module defines functions and classes to parse docstrings into structured data."""
import re
from typing import Any, List, Optional, Pattern, Sequence, Tuple

from pytkdocs.parsers.docstrings.base import AnnotatedObject, Parameter, Parser, Section, empty

TITLES_PARAMETERS: Sequence[str] = ("args:", "arguments:", "params:", "parameters:")
"""Titles to match for "parameters" sections."""

TITLES_EXCEPTIONS: Sequence[str] = ("raise:", "raises:", "except:", "exceptions:")
"""Titles to match for "exceptions" sections."""

TITLES_RETURN: Sequence[str] = ("return:", "returns:")
"""Titles to match for "returns" sections."""


RE_GOOGLE_STYLE_ADMONITION: Pattern = re.compile(r"^(?P<indent>\s*)(?P<type>[\w-]+):((?:\s+)(?P<title>.+))?$")
"""Regular expressions to match lines starting admonitions, of the form `TYPE: [TITLE]`."""


class Google(Parser):
    """A Google-style docstrings parser."""

    def __init__(self, replace_admonitions: bool = True) -> None:
        """
        Initialization method.

        Arguments:
            replace_admonitions: Whether to replace admonitions by their Markdown equivalent.
        """
        super().__init__()
        self.replace_admonitions = replace_admonitions

    def parse_sections(self, docstring: str) -> List[Section]:  # noqa: D102
        sections = []
        current_section = []

        in_code_block = False

        lines = docstring.split("\n")
        i = 0

        while i < len(lines):
            line_lower = lines[i].lower()

            if in_code_block:
                if line_lower.lstrip(" ").startswith("```"):
                    in_code_block = False
                current_section.append(lines[i])

            elif line_lower in TITLES_PARAMETERS:
                if current_section:
                    if any(current_section):
                        sections.append(Section(Section.Type.MARKDOWN, "\n".join(current_section)))
                    current_section = []
                section, i = self.read_parameters_section(lines, i + 1)
                if section:
                    sections.append(section)

            elif line_lower in TITLES_EXCEPTIONS:
                if current_section:
                    if any(current_section):
                        sections.append(Section(Section.Type.MARKDOWN, "\n".join(current_section)))
                    current_section = []
                section, i = self.read_exceptions_section(lines, i + 1)
                if section:
                    sections.append(section)

            elif line_lower in TITLES_RETURN:
                if current_section:
                    if any(current_section):
                        sections.append(Section(Section.Type.MARKDOWN, "\n".join(current_section)))
                    current_section = []
                section, i = self.read_return_section(lines, i + 1)
                if section:
                    sections.append(section)

            elif line_lower.lstrip(" ").startswith("```"):
                in_code_block = True
                current_section.append(lines[i])

            else:
                if self.replace_admonitions and not in_code_block and i + 1 < len(lines):
                    match = RE_GOOGLE_STYLE_ADMONITION.match(lines[i])
                    if match:
                        groups = match.groupdict()
                        indent = groups["indent"]
                        if lines[i + 1].startswith(indent + " " * 4):
                            lines[i] = f"{indent}!!! {groups['type'].lower()}"
                            if groups["title"]:
                                lines[i] += f' "{groups["title"]}"'
                current_section.append(lines[i])

            i += 1

        if current_section:
            sections.append(Section(Section.Type.MARKDOWN, "\n".join(current_section)))

        return sections

    @staticmethod
    def is_empty_line(line) -> bool:
        """
        Tell if a line is empty.

        Arguments:
            line: The line to check.

        Returns:
            True if the line is empty or composed of blanks only, False otherwise.
        """
        return not line.strip()

    def read_block_items(self, lines: List[str], start_index: int) -> Tuple[List[str], int]:
        """
        Parse an indented block as a list of items.

        The first indentation level is used as a reference to determine if the next lines are new items
        or continuation lines.

        Arguments:
            lines: The block lines.
            start_index: The line number to start at.

        Returns:
            A tuple containing the list of concatenated lines and the index at which to continue parsing.
        """
        if start_index >= len(lines):
            return [], start_index

        i = start_index
        items: List[str] = []

        # skip first empty lines
        while self.is_empty_line(lines[i]):
            i += 1

        # get initial indent
        indent = len(lines[i]) - len(lines[i].lstrip())

        if indent == 0:
            # first non-empty line was not indented, abort
            return [], i - 1

        # start processing first item
        current_item = [lines[i][indent:]]
        i += 1

        # loop on next lines
        while i < len(lines):
            line = lines[i]

            if line.startswith(indent * 2 * " "):
                # continuation line
                current_item.append(line[indent * 2 :])

            elif line.startswith((indent + 1) * " "):
                # indent between initial and continuation: append but add error
                cont_indent = len(line) - len(line.lstrip())
                current_item.append(line[cont_indent:])
                self.error(
                    f"Confusing indentation for continuation line {i+1} in docstring, "
                    f"should be {indent} * 2 = {indent*2} spaces, not {cont_indent}"
                )

            elif line.startswith(indent * " "):
                # indent equal to initial one: new item
                items.append("\n".join(current_item))
                current_item = [line[indent:]]

            elif self.is_empty_line(line):
                # empty line: preserve it in the current item
                current_item.append("")

            else:
                # indent lower than initial one: end of section
                break

            i += 1

        if current_item:
            items.append("\n".join(current_item).rstrip("\n"))

        return items, i - 1

    def read_block(self, lines: List[str], start_index: int) -> Tuple[str, int]:
        """
        Parse an indented block.

        Arguments:
            lines: The block lines.
            start_index: The line number to start at.

        Returns:
            A tuple containing the list of lines and the index at which to continue parsing.
        """
        if start_index >= len(lines):
            return "", start_index

        i = start_index
        block: List[str] = []

        # skip first empty lines
        while self.is_empty_line(lines[i]):
            i += 1

        # get initial indent
        indent = len(lines[i]) - len(lines[i].lstrip())

        if indent == 0:
            # first non-empty line was not indented, abort
            return "", i - 1

        # start processing first item
        block.append(lines[i].lstrip())
        i += 1

        # loop on next lines
        while i < len(lines) and (lines[i].startswith(indent * " ") or self.is_empty_line(lines[i])):
            block.append(lines[i][indent:])
            i += 1

        return "\n".join(block).rstrip("\n"), i - 1

    def read_parameters_section(self, lines: List[str], start_index: int) -> Tuple[Optional[Section], int]:
        """
        Parse a "parameters" section.

        Arguments:
            lines: The parameters block lines.
            start_index: The line number to start at.

        Returns:
            A tuple containing a `Section` (or `None`) and the index at which to continue parsing.
        """
        parameters = []
        type_: Any
        block, i = self.read_block_items(lines, start_index)

        for param_line in block:
            try:
                name_with_type, description = param_line.split(":", 1)
            except ValueError:
                self.error(f"Failed to get 'name: description' pair from '{param_line}'")
                continue

            description = description.lstrip()

            if " " in name_with_type:
                name, type_ = name_with_type.split(" ", 1)
                type_ = type_.strip("()")
                if type_.endswith(", optional"):
                    type_ = type_[:-10]
            else:
                name = name_with_type
                type_ = empty

            default = empty
            annotation = type_
            kind = None

            try:
                signature_param = self.object_signature.parameters[name.lstrip("*")]  # type: ignore
            except (AttributeError, KeyError):
                self.error(f"No type annotation for parameter '{name}'")
            else:
                if signature_param.annotation is not empty:
                    annotation = signature_param.annotation
                if signature_param.default is not empty:
                    default = signature_param.default
                kind = signature_param.kind

            parameters.append(
                Parameter(name=name, annotation=annotation, description=description, default=default, kind=kind)
            )

        if parameters:
            return Section(Section.Type.PARAMETERS, parameters), i

        self.error(f"Empty parameters section at line {start_index}")
        return None, i

    def read_exceptions_section(self, lines: List[str], start_index: int) -> Tuple[Optional[Section], int]:
        """
        Parse an "exceptions" section.

        Arguments:
            lines: The exceptions block lines.
            start_index: The line number to start at.

        Returns:
            A tuple containing a `Section` (or `None`) and the index at which to continue parsing.
        """
        exceptions = []
        block, i = self.read_block_items(lines, start_index)

        for exception_line in block:
            try:
                annotation, description = exception_line.split(": ", 1)
            except ValueError:
                self.error(f"Failed to get 'exception: description' pair from '{exception_line}'")
            else:
                exceptions.append(AnnotatedObject(annotation, description.lstrip(" ")))

        if exceptions:
            return Section(Section.Type.EXCEPTIONS, exceptions), i

        self.error(f"Empty exceptions section at line {start_index}")
        return None, i

    def read_return_section(self, lines: List[str], start_index: int) -> Tuple[Optional[Section], int]:
        """
        Parse an "returns" section.

        Arguments:
            lines: The return block lines.
            start_index: The line number to start at.

        Returns:
            A tuple containing a `Section` (or `None`) and the index at which to continue parsing.
        """
        text, i = self.read_block(lines, start_index)

        if self.object_signature:
            annotation = self.object_signature.return_annotation
        else:
            annotation = self.object_type

        if annotation is empty:
            if not text:
                self.error("No return type annotation")
            else:
                try:
                    type_, text = text.split(":", 1)
                except ValueError:
                    self.error("No type in return description")
                else:
                    annotation = type_.lstrip()
                    text = text.lstrip()

        if annotation is empty and not text:
            self.error(f"Empty return section at line {start_index}")
            return None, i

        return Section(Section.Type.RETURN, AnnotatedObject(annotation, text)), i
