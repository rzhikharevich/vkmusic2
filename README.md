# vkmusic2

## Introduction

vkmusic2 is the second version of [vkmusic][1], a tool to download audio from 
vk.com.

Unfortunately, it's no longer possible to query the official API to download 
audio files, so this iteration, unlike the first one, instead does the same 
things the official web version does, i.e. calls the private API. The downside 
is in that vkmusic2 requires your login credentials (as apposed to using API 
tokens) to impersonate the web version. Breakage is also more likely this way.

[1]: https://github.com/rzhikharevich/vkmusic

## Missing Things

* a Python implementation of decode-uri.js (which is an excerpt from the 
official web version; that's not completely legal to use that actually...)
* access to audios outside the current user's list
