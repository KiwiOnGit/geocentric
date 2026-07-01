from geocentric.agent.fallback_parser import extract_tool_calls
from geocentric.agent.tools import default_registry


def registry():
    return default_registry()


def test_json_fence_format_is_parsed():
    text = 'Sure.\n```tool_call\n{"name": "write_file", "arguments": {"path": "x.py", "content": "print(1)"}}\n```\n'
    calls = extract_tool_calls(text, registry())
    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].arguments == {"path": "x.py", "content": "print(1)"}


def test_json_fence_takes_precedence_over_legacy_tags():
    text = (
        '```tool_call\n{"name": "grep", "arguments": {"pattern": "foo"}}\n```\n'
        '<read_file>ignored.txt</read_file>'
    )
    calls = extract_tool_calls(text, registry())
    assert len(calls) == 1
    assert calls[0].name == "grep"


def test_legacy_write_file_tag_maps_filename_attr_to_path():
    text = '<write_file filename="hello.txt">Hello world</write_file>'
    calls = extract_tool_calls(text, registry())
    assert len(calls) == 1
    assert calls[0].name == "write_file"
    assert calls[0].arguments == {"path": "hello.txt", "content": "Hello world"}


def test_legacy_run_command_tag():
    text = "<run_command>ls -la</run_command>"
    calls = extract_tool_calls(text, registry())
    assert len(calls) == 1
    assert calls[0].name == "run_command"
    assert calls[0].arguments == {"command": "ls -la"}


def test_legacy_move_file_maps_from_to_attrs():
    text = '<move_file from="a.txt" to="b.txt" />'
    calls = extract_tool_calls(text, registry())
    assert len(calls) == 1
    assert calls[0].arguments == {"source": "a.txt", "destination": "b.txt"}


def test_multiple_legacy_tags_preserve_document_order():
    text = '<write_file filename="a.txt">A</write_file><write_file filename="b.txt">B</write_file>'
    calls = extract_tool_calls(text, registry())
    assert [c.arguments["path"] for c in calls] == ["a.txt", "b.txt"]


def test_no_tool_calls_in_plain_text():
    assert extract_tool_calls("just chatting, no tools here", registry()) == []


def test_malformed_json_fence_is_ignored_not_raised():
    text = "```tool_call\n{not valid json\n```"
    assert extract_tool_calls(text, registry()) == []
