import openai

client = openai.OpenAI()

server_url = "https://100.121.55.88:11434/v1"    
client.base_url = server_url
api_key = "ollama"

client.api_key = api_key

system_prompt = """
You are a data organizer. You are given a transcript. 
Your task is to organize the data in a structured format.
The transcript may contain multiple categories of data.
Do not repeat categories that are already identified.
Some examples of categories are:



Don't include categories that are not identified in the transcript.
Do not alter data in the transcript.
Do not add any additional information to the transcript.
Please respond only in this markdown format:

# Action Items
- Example Action Item

# Notes
- Example Note

# Decisions
- Example Decision

"""

transcript = """
Okay, so today I need to get some work done regarding Fred Reno. I need to get the voice flow dashboard up and running so that I can give Marisa her reports. And then I need to lock down the final draft of the SOW for Tim.
"""

response = client.chat.completions.create(
    model="qwen3.6:35b-mlx",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": transcript}
    ]
)

print(response.choices[0].message.content)