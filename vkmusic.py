#!/usr/bin/env python3

from argparse import ArgumentParser
from getpass import getpass
import requests as req
from bs4 import BeautifulSoup
import json
import os
import sys
from pyduktape import DuktapeContext

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module='bs4')

def soup(s):
    return BeautifulSoup(s, "html.parser")

def find_after(s, prefix):
    i = s.find(prefix)
    return s[i+len(prefix):] if i != -1 else None

def find_enclosed(s, prefix, *args):
    if len(args) == 0:
        postfix = prefix
    elif len(args) == 1:
        postfix = args[0]
    else:
        assert False

    s1 = find_after(s, prefix)
    if s1 is None:
        return None
    
    j = s1.find(postfix)
    if j == -1:
        return None

    return s1[:j]

def resp_assert(c, *args):
    if len(args) == 0:
        if not c:
            raise BadResponseException()
    elif len(args) == 1:
        if not c:
            raise BadResponseException(args[0])
    else:
        assert False

def windows(it, n):
    s = []

    for x in it:
        if len(s) == n:
            yield s
            s = [x]
        else:
            s.append(x)

    if len(s) > 0:
        yield s
        
# TODO: reimplement the JS code in Python
        
dt_ctx = DuktapeContext()
dt_ctx.eval_js_file("decode-uri.js")

def weird_decode(s):
    return dt_ctx.eval_js(f"decode_uri('{s}')")
        
class Session:
    def __init__(self):
        self._session = req.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13) AppleWebKit/604.1.34 (KHTML, like Gecko) Version/11.0 Safari/604.1.34"
        })
        self._uid = None

    @classmethod
    def with_creds(cls, email, password):
        s = cls()

        return AuthResult(s, s._init_creds(email, password))

    def _init_creds(self, email, password):
        ip_h, lg_h = self._get_login_params()

        resp_assert(ip_h and lg_h)
        
        complete = self._login(email, password, ip_h, lg_h)

        if complete:
            self._uid = self._get_uid()

        return complete

    def _get_login_params(self):
        resp = self._session.get("https://vk.com")

        doc = soup(resp.text)

        form = doc.find(id="quick_login_form")
        resp_assert(form is not None)
        
        val = lambda s: (form.find("input", {"name": s}) or {}).get("value")
        return val("ip_h"), val("lg_h")

    def _login(self, email, password, ip_h, lg_h):
        resp = self._session.post("https://login.vk.com/?act=login", data={
            "act": "login",
            "role": "al_frame",
            "origin": "https://vk.com",
            "email": email,
            "pass": password,
            "ip_h": ip_h,
            "lg_h": lg_h
        })

        doc = soup(resp.text)

        script_elem = doc.find("script")
        resp_assert(script_elem is not None)
        
        script = repr(script_elem.text)

        if script.find("onLoginDone") != -1:
            return True
        elif script.find("/login?act=authcheck") != -1:
            return False
        else:
            raise BadCredentialsException()

    def _provide_auth_code(self, ac_hash, code):
        resp = self._session.post("https://vk.com/al_login.php", data={
            "act": "a_authcheck_code",
            "code": code,
            "remember": "true",
            "hash": ac_hash
        })

        return resp.url == "https://vk.com/feed"

    def _get_auth_check_hash(self):
        resp = self._session.get("https://vk.com/login?act=authcheck")

        doc = soup(resp.text)

        pfx = "hash: "

        for script in doc.find_all("script"):
            s = find_enclosed(script.text, "hash: '", "'")

            if s is not None:
                return s

        raise BadResponseException()

    def _get_uid(self):
        resp = self._session.get("https://vk.com/settings")

        doc = soup(resp.text)
        
        line = doc.find(id="chgaddr")
        if line is None:
            raise BadResponseException()

        hint = line.find("div", {"class": "settings_row_hint"})
        resp_assert(hint is not None)

        uid_tag = hint.find("b")
        resp_assert(uid_tag is not None)

        return uid_tag.text

    _cookie_ids = ["remixttpid", "remixstid", "remixsid"]
    
    def serialize(self):
        kv = dict(map(
            lambda k: (k, self._session.cookies.get(k)),
            Session._cookie_ids
        ))

        kv["uid"] = self._uid
        
        return json.dumps(kv)

    @classmethod
    def deserialize(cls, s):
        session = cls()

        kv = json.loads(s)
        
        for id in cls._cookie_ids:
            session._session.cookies.set(id, kv[id], domain=".vk.com")

        session._uid = kv["uid"]
            
        return session

    def fetch_playlist_list(self):
        return list(self._fetch_playlist_list_gen())
    
    def _fetch_playlist_list_gen(self):
        resp = self._session.get("https://vk.com/audio?section=playlists")

        doc = soup(resp.text)

        items = doc.find("div", {"class": "_audio_page_block__playlists_items"})
        resp_assert(items is not None)

        for item in items.children:
            cover = item.find("a", {"class": "audio_pl__cover"})
            resp_assert(cover is not None)

            href = cover.get("href")
            resp_assert(href is not None)

            pfx = "audio_playlist"
            
            pfx_base = href.find(pfx)
            resp_assert(pfx_base != -1)

            owner_id_etc = href[pfx_base+len(pfx):]

            sep_idx = owner_id_etc.find("_")
            resp_assert(sep_idx != -1)

            owner_id = owner_id_etc[:sep_idx]

            pl_id = owner_id_etc[sep_idx+1:]

            title = item.find("a", {"class": "audio_pl__title"})
            resp_assert(title is not None)

            yield Playlist(owner_id, pl_id, title.string)
            
    def fetch_audio_list(self, pl):
        return \
          self._fetch_partial_audio_list(pl, 0) +\
          self._fetch_partial_audio_list(pl, 100)

    def _fetch_partial_audio_list(self, pl, offset):
        if pl is None:
            oid = self._uid
            pid = "-1"
        else:
            oid = pl.owner_id
            pid = pl.id
        
        resp = self._session.post("https://vk.com/al_audio.php", data={
            "act": "load_section",
            "al": "1",
            "claim": "0",
            "offset": offset,
            "owner_id": oid,
            "playlist_id": pid,
            "type": "playlist"
        })
        
        json_text = find_enclosed(resp.text, "<!json>", "<!>")
        resp_assert(json_text is not None)

        audios = json.loads(json_text)["list"]

        return list(map(Audio.from_raw_array, audios))

    def fetch_audio_urls(self, audios):
        resp = self._session.post("https://vk.com/al_audio.php", data={
            "act": "reload_audio",
            "al": "1",
            "ids": ",".join(map(lambda a: a.id, audios))
        })

        json_text = find_enclosed(resp.text, "<!json>", "<!>")
        resp_assert(json_text is not None)

        audios_ = json.loads(json_text)
        
        return list(map(Audio.from_raw_array, audios_))

    def download(self, url):
        return self._session.get(url)
    
class AuthFailureException(Exception):
    pass
    
class BadResponseException(AuthFailureException):
    pass

class BadCredentialsException(AuthFailureException):
    pass

class BadAuthCode(AuthFailureException):
    pass

class AuthResult:
    def __init__(self, session, is_complete):
        self._session = session
        self._is_complete = is_complete

    def provide_auth_code(self, f):
        if not self.is_complete():
            ac_hash = self._session._get_auth_check_hash()

            if not self._session._provide_auth_code(ac_hash, f()):
                raise BadCredentialsException()

            self._session._uid = self._session._get_uid()

        return self._session

    def session(self):
        return self._session if self.is_complete() else None
    
    def is_complete(self):
        return self._is_complete

class Playlist:
    def __init__(self, owner_id, id, title):
        self.owner_id = owner_id
        self.id = id
        self.title = title
    
class Audio:
    def __init__(self, id, author, title, url):
        self.id = id
        self.author = author
        self.title = title
        self.url = url

    @classmethod
    def from_raw_array(cls, a):
        return cls(
            f"{a[1]}_{a[0]}",
            soup(a[4]).string,
            soup(a[3]).string,
            weird_decode(a[2]) if len(a[2]) > 0 else None
        )

def get_data_root():
    if sys.platform == "windows":
        return os.getcwd()
    else:
        default = os.path.expanduser("~/.local/share")
        return os.environ.get("XDG_DATA_HOME", default) + "/vkmusic"
    
if __name__ == "__main__":
    ap = ArgumentParser()

    ap.add_argument("-e", "--email", help="email or phone number")

    ap.add_argument(
        "-r", "--remember",
        help="save the session token before exiting",
        action="store_true"
    )

    ap.add_argument(
        "-p", "--playlist",
        help="playlist to scan"
    )
    
    ap.add_argument(
        "-a", "--audios",
        help=(
            "space-separated list of audios to download, "
            "entry format: [AUTHOR][:TITLE]"
        ),
        nargs="+"
    )

    args = ap.parse_args()

    data_root = get_data_root()
    session_path = os.path.join(data_root, "session.json")
    
    if not os.path.exists(data_root):
        os.makedirs(data_root)
    
    if args.email:
        password = getpass(prompt="Password: ")
    
        def get_code():
            return getpass(prompt="Two-factor authentication code: ")
    
        session = Session.with_creds(args.email, password) \
          .provide_auth_code(get_code)

        if args.remember:
            with open(session_path, "wt") as session_file:
                session_file.write(session.serialize())
    elif os.path.exists(session_path):
        with open(session_path, "rt") as session_file:
            session = Session.deserialize(session_file.read())
    else:
        print((
            "Neither a session file was found nor an email was provided. "
            "Consider using the '--email' flag."
        ))

        exit(1)

    if args.playlist is None and args.audios is None:
        if args.email is None:
            ap.print_help()
            exit(1)
        else:
            exit(0)

    if args.playlist is not None:
        playlists = session.fetch_playlist_list()

        try:
            playlist = next(pl for pl in playlists if pl.title == args.playlist)
        except StopIteration:
            print("Playlist not found.")
            exit(1)
    else:
        playlist = None

    audio_list = session.fetch_audio_list(playlist)

    if args.audios is None:
        downloads = audio_list
    else:
        filter_table = {}
        titles = set()

        for audio in args.audios:
            elems = audio.split(":", maxsplit=1)

            if len(elems) == 1:
                filter_table[elems[0]] = True
            elif len(elems[0]) > 0:
                if elems[0] not in filter_table:
                    filter_table[elems[0]] = set()

                if len(elems[1]) == 0:
                    filter_table[elems[0]] = True
                elif isinstance(filter_table.get(elems[0]), set):
                    filter_table[elems[0]].add(elems[1])
            else:
                titles.add(elems[1])
    
        def audio_pred(a):
            if a.title in titles:
                return True
            else:
                filt = filter_table.get(a.author)
                return filt is not None and (filt == True or a.title in filt)

        downloads = filter(audio_pred, audio_list)

    dirs = set(os.listdir("."))

    print("Downloading:")
    
    for download_chunk in windows(downloads, 10):
        al_with_urls = session.fetch_audio_urls(download_chunk)

        for audio in al_with_urls:
            # TODO: Windows compat
            author_dir = audio.author.replace("/", "|")
            
            if author_dir not in dirs:
                os.mkdir(author_dir)
                dirs.add(author_dir)

            title_pc = audio.title.replace("/", "|") + ".mp3"

            path = os.path.join(author_dir, title_pc)

            if not os.path.exists(path):
                print(f" * {audio.title} by {audio.author}.")

                resp = session.download(audio.url)
            
                with open(path, "wb") as file:
                    file.write(resp.content)
