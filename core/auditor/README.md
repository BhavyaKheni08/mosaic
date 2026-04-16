# Auditor Agent

## What is this?
The Auditor Agent is a background robot for the Mosaic project. Its main job is to double-check old facts in our system to see if they are still true.

## Why do we need it?
Information gets old. A fact we learned a year ago might not be true today. Over time, the system naturally starts to trust old facts less and less. We call this "decay". 

## How does it work?
1. **Find Old Facts**: The agent looks for facts that have decayed and we don't trust much anymore.
2. **Prioritize**: It checks the most important facts first.
3. **Ask AI**: It asks a smart AI (like Llama 3) to research the fact and see if it is still correct.
4. **Update**: It updates the system with the fresh information and saves a log of what it did.

## What do the files do?
* `decay.py`: Does the math to slowly lower our trust in old facts over time.
* `agent.py`: The actual robot that runs in the back and checks the facts.
* `logger.py`: Keeps a clear record of every change the robot makes.
* `models.py`: Defines the basic shapes of our data (like what a "Fact" looks like).
* `utils.py`: Helps catch and log errors safely without crashing the system.
* `integration.md`: A guide on how to connect this robot to real databases later.

## Safe and Simple
If the AI fails or the database breaks, the Auditor is designed to stay safe. It will not delete good data by mistake. It just leaves the data alone and tries again later.
