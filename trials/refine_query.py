import json
import subprocess
import re

def refine_structured_query_with_answers(original_input, answers, previous_query):
    """Regenerate final structured query after follow-up answers."""
    prompt = f"""
        You're a structured query extractor for shopping assistants.

        Given:
        - Original user input
        - User's answers to follow-up questions
        - Previously extracted structured query

        Regenerate a full structured query with refined filters, goal, and query fields.

        ### Original Input:
        {original_input}

        ### Previous Structured Query:
        {json.dumps(previous_query, indent=2)}

        ### Follow-up Answers:
        {json.dumps(answers, indent=2)}

        Return only the updated structured query as JSON:
    """
    try:
        process = subprocess.run(
            ["ollama", "run", "llama3:8b-instruct-q8_0"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=30
        )
        stdout = process.stdout
        json_match = re.search(r'\{[\s\S]*\}', stdout)
        return json.loads(json_match.group(0)) if json_match else previous_query
    except Exception as e:
        print(f"Failed to refine structured query: {e}")
        return previous_query
