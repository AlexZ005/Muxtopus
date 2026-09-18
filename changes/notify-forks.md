## notifications: the phone answers a fork

- **An unanswered question can be answered from Telegram.** Each fork arrives
  as its own message with a button per option (★ on the recommended one) and
  **✎ type**; a plain reply to the message works too. The answer is written
  into the QUESTIONS file as `**Answer (user via telegram, <date>):**`, into
  the right fork even if the lane rewrote the file meanwhile, and never over
  an answer given at the machine. The last answer marks the file ANSWERED and
  tells the lane, if its window is open and idle.
- `/questions` lists the unanswered files as buttons; `/pending` now sends
  the forks themselves; the watchdog's questions push carries the buttons too.
