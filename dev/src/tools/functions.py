# Functions for AVA system
from __future__ import annotations
import unicodedata
from openai.types.responses import ResponseTextDeltaEvent

async def handle_stream_events(result):
    async for event in result.stream_events():

        if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
            # # raw text generations of model
            # print(event.data.delta, end="", flush=True)
            pass
        
        elif event.type == "agent_updated_stream_event":
            print("-- Agent Updated.")
            print(event.new_agent.name) # example of output: 'Planner Agent'

        elif event.type == "run_item_stream_event":
            if event.item.type == "tool_call_item":
                print("-- Tool Called.")
                print(f"Tool name: {event.item.raw_item.name}")
                print(f"Arguments: {event.item.raw_item.arguments}")

        elif event.type in ("completed_event", "final_output_event"):
            print("-- Execution completed. Exiting stream loop.")
            break

def read_instructions(file_name: str) -> str:
    """Read and return the contents of a file.

    Args:
        file_path (str): The path to the file to be read.

    Returns:
        str: The complete contents of the file as a string.

    Raises:
        FileNotFoundError: If the specified file does not exist.
        IOError: If there are issues reading the file.
    """
    with open(file_name, "r", encoding="utf-8", errors="strict") as f:
        text = f.read()
    return unicodedata.normalize("NFC", text)
