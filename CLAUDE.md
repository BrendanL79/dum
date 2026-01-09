The initial commit in this repo (bebfe84adc66c1c4048c354e5538f63150feb142) contains the result of submitting the following prompt to Claude Opus 4.1 on 2025-09-28:
I want to set up an auto-update mechanism for my Docker container images. But not simply grabbing "latest" at intervals. I also want to save, for each image, one of the other build tags that points to the same image as "latest". Each image will have an associated regex that defines the tag I want to save. For example, for the current "latest" of "linuxserver/calibre", the associated tag I would want is "v8.11.1-ls358", with a regex of "/v[0-9]\.[0-9]\.[0-9]-ls[0-9]/".  The server I'm doing this on is amd64-based but I would prefer an architecture-agnostic solution.

I then followed up with:
looks like we still need a way to track the idea that I want a standard tag ("latest" for most but not all images) in addition to the regex-based tag

and committed the result (63ddb3ded0fd1f4d4e68c78a78c5deeeb8ee28bc)

As of this writing the next thing I want to add is testability, ideally via a "dry run" option that just outputs to a log file and/or console what it would do, without actually pulling any new images or deleting/modifying any existing.

