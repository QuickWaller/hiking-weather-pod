

Comments:
- We will need to find a db for recent labels. This becomes important when we eventually want to test the MCU based on real-life observations. This db + weather info cannot have more than 1-2 days lag time.
- We are going to want to consider the different kinds of error for each final (merged cell) and for each trained but unmerged cell. I'd like to know which regions are accurate/inaccurate. Which regions struggle with false positives. Which regions struggle with false negatives. etc.
- MCU to laptop connections where we transfer logs and validate should be written in auch a way that it can be implemented on any computer (particularly win11 and a linux RPi)
- We can get creative with logs and sensor reading intervals, this hasnt necessarily been decided yet and we can discuss later.
- Features we already have can be utilised to load sprites. e.g elavation and later ground cover -> walking in alpine forest. not too fussed here, this can ultimately come last.
- This repo has become more of a pod repo not a cyber deck repo. This is not a mistake, as we worked on it, it became clear that the pod is fhe focus. we may decide to scrap the cyber deck completely. Either way it is not the focus until the pod is wrapped up.
- We also definitely want feature importance, we can muck around with different features until we get the right ones.
