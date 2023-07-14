#!/usr/bin/env python3

import os, cmd, json, configparser, colorsys
from pathlib import Path
from itertools import groupby
from collections import defaultdict
from typing import NamedTuple, Hashable, Iterable

from rich.console import Console
from rich.tree import Tree
from rich.table import Table
from rich.text import Text
from rich.style import Style
from rich.color import Color

from multiset import FrozenMultiset
from google.protobuf.descriptor_pb2 import (
    FileDescriptorSet,
    FileDescriptorProto,
    DescriptorProto,
    FieldDescriptorProto,
    EnumDescriptorProto
)

CONFIG_FILE = Path("config.ini")
OUTPUT_DIR = Path("output")

SignType = FrozenMultiset | frozenset | tuple | str

class FieldTuple(NamedTuple):
    label_type: str
    signature: SignType

class MapEntry(NamedTuple):
    key: SignType
    value: SignType

Signature = SignType | FieldTuple | MapEntry

console = Console()
print = console.print

config = configparser.ConfigParser(allow_no_value=True)
config.optionxform = str
# These comments look better in the auto-generated config.ini, just ignore how ugly this looks
config["ProtoMatcher"] = {
    "# Generate descriptors using protoc --descriptor_set_out=FILE": None,
    "REF_DESCRIPTOR_FILE": "ref_data\\3.4.0_desc.pb",
    "OBS_DESCRIPTOR_FILE": "",

    "\n# Sequential list of protos (as .json)": None,
    "REF_PROTO_LIST": "ref_data\\3.4.0_list.json",
    "OBS_PROTO_LIST": "",

    "\n# Leave empty if no set package, otherwise enter the package name (this will affect type lookups!)": None,
    "PACKAGE_NAME": "",

    "\n# Max depth when printing out a signature (0 for no limit)": None,
    "MAX_SIG_DEPTH": 0,

    "\n# Max number of protos displayed when matching": None,
    "MAX_DISPLAY_MATCHES": 5,

    "\n# Max percentage score of a signature match": None,
    "THRESHOLD": 0.5,

    "\n# If True, empty message types will be considered as bytes instead when generating signatures.": None,
    "DEFAULT_EMPTY_TO_BYTES": True
}
options = config["ProtoMatcher"]

#region Utils
def save_config():
    with open(CONFIG_FILE, "w") as f:
        config.write(f)

def change_option(option: str, value: str):
    options[option] = value
    save_config()

def load_config():
    config_exist = config.read("config.ini")
    if not config_exist:
        save_config()
        print(f"Generated config.ini in {os.getcwd()}")
    if not options["OBS_DESCRIPTOR_FILE"]:
        obs_desc_path = input("Enter the path to the obfuscated proto descriptor file:\n")
        change_option("OBS_DESCRIPTOR_FILE", obs_desc_path)
    if not options["OBS_PROTO_LIST"]:
        obs_list_path = input("Enter the path to the obfuscated proto list file:\n")
        change_option("OBS_PROTO_LIST", obs_list_path)

def get_descriptor_set(descriptor_path: str) -> FileDescriptorSet:
    with open(descriptor_path, "rb") as f:
        return FileDescriptorSet.FromString(f.read())
    
def get_proto_list(list_path: str) -> list[str]:
    with open(list_path) as f:
        return json.load(f)

def strip_proto_name(name: str) -> str:
    return name.removeprefix(".").removeprefix(options["PACKAGE_NAME"]).removesuffix(".proto")

def is_obs_name(name: str) -> bool:
    return name.isalpha() and name.isupper()

def get_sig_rlen(signature: Signature) -> int:
    sig_type = type(signature)
    if sig_type in (FrozenMultiset, tuple):
        total_len = 0
        for i in signature:
            total_len += get_sig_rlen(i)
        return total_len
    elif sig_type == frozenset:
        return len(signature)
    return 1
#endregion

#region Data Prettification
def to_proto_name(name: str) -> str:
    return f"[aquamarine3]{name}.proto[/]"

def short_hash(obj: Hashable) -> Text:
    return Text(f"{abs(hash(obj)):X}"[:9], "dark_turquoise")

def colored_percent(percent: float) -> Text:
    gradient_rgb = [i * 255 for i in 
    colorsys.hsv_to_rgb(percent * 0.3, 0.5, 1)]
    style = Style(color=Color.from_rgb(*gradient_rgb))
    return Text(f"{percent * 100:.3f}"[:5] + "%", style)

def ints2ranges(iterable: Iterable) -> list[tuple]:
    ranges: list[tuple] = []
    iterable = sorted(set(iterable))
    for _, group in groupby(enumerate(iterable), lambda t: t[1] - t[0]):
        group = list(group)
        ranges.append((group[0][1], group[-1][1]))
    return ranges

def print_sig_tree(signature: Signature):
    sig_type = "message" if type(signature) == FrozenMultiset else "enum"
    sig_tree = Tree(Text.assemble((sig_type, "blue"), " (", short_hash(signature), ")"))
    max_depth = options.getint("MAX_SIG_DEPTH", 0)
    sig_depth = 1

    def grow_sig_tree(sig: Signature, parent: Tree, depth=1):
        nonlocal sig_depth
        sig_depth = max(sig_depth, depth)
            
        def unpack_field(field: str | FieldTuple, fsize: int = 0, add_info: str = ""):
            fsize_txt = Text.assemble(": ", (str(sig[field]), "steel_blue1")) if fsize else ""
            if type(field) == FieldTuple:
                sig_hash = short_hash(field.signature)
                is_message = field.label_type.endswith("message")
                depth_txt = f"{depth} " if is_message else ""
                branch = parent.add(Text.assemble(
                    add_info, depth_txt, (field.label_type, "blue"), " (", sig_hash, ")", fsize_txt))
                if max_depth > 0 and depth >= max_depth and is_message: return
                grow_sig_tree(field.signature, branch, depth + int(is_message))
            else:
                parent.add(Text.assemble(add_info, (field, "blue"), fsize_txt))

        if type(sig) in [FrozenMultiset, FieldTuple]:
            fields = sig.distinct_elements() if type(sig) == FrozenMultiset else sig
            for field in fields:
                fsize = sig[field] if type(sig) == FrozenMultiset and sig[field] > 1 else 0
                unpack_field(field, fsize)

        elif type(sig) == MapEntry:
            unpack_field(sig.key, add_info="key: ")
            unpack_field(sig.value, add_info="value: ")

        elif type(sig) == frozenset: # enum values
            parent.add(Text(str(ints2ranges(sig)), "aquamarine3"))

    grow_sig_tree(signature, sig_tree)
    print(sig_tree, f"Signature Tree Depth: {sig_depth}")

def sig_proto_table() -> Table:
    table = Table(
        row_styles=[
            Style(bgcolor="grey11"),
            Style(bgcolor="grey7")
        ])
    table.add_column("Sign Hash")
    table.add_column("Obfuscated", width=17)
    table.add_column("Reference")
    return table
#endregion

def compare_sigs(sig1: Signature, sig2: Signature) -> float:
    # Possible TODO: just doing an intersection means that messages/enums/oneofs that-
    # don't have exactly matching signatures don't count towards the score.
    # Perhaps there can be a separate counter for these types? (only for scoring)
    # So even if the signature doesn't match, there's still a point for each message/enum/oneof
    sig1_len = len(sig1)
    sig2_len = len(sig2)
    intersection = len(sig1 & sig2)
    # Probably should make this a config option. Using the len ratio to affect the score means
    # a new proto that could've been a match but has new fields will score less.
    len_ratio = min(sig1_len, sig2_len) / max(sig1_len, sig2_len)
    return (intersection / sig1_len) * len_ratio

def get_matches(proto_name: str, match_sig: Signature, proto2sig_map: dict[str, Signature], proto_list: list[str]):
    threshold = options.getfloat("THRESHOLD", 0.5)
    print(f"Scoring Threshold:", colored_percent(threshold))
    score_map: dict[str, float] = {}
    
    for name, sig in proto2sig_map.items():
        if "." in name: continue # Skip nested types
        score = compare_sigs(match_sig, sig)
        if score < threshold: continue
        score_map[name] = score

    if not score_map:
        return print("No matches found. :cry:")
    
    def sort_key(tup: tuple[str, float]) -> float:
        idx_weight = 1 -((proto_list.index(tup[0]) + 1) / len(proto_list))
        return tup[1] + idx_weight * 0.5
    
    matches_sorted = sorted(score_map.items(), key=sort_key, reverse=True)
    matches_view = matches_sorted[:options.getint("MAX_DISPLAY_MATCHES")]
    print(f"Matches for {to_proto_name(proto_name)} (showing {len(matches_view)}/{len(score_map)}):")
    for name, score in matches_view:
        place = proto_list.index(name)
        print(Text.assemble(" " * 3, "(", colored_percent(score), ")"), to_proto_name(name), f"[{place}]")

def generate_signatures(descriptor_set: FileDescriptorSet) -> tuple[
                        dict[str, Signature], defaultdict[Signature, list[str]]]:
    descriptor_map: dict[str, FileDescriptorProto] = {}
    proto2sig_map: dict[str, Signature] = {}
    sig2proto_map: defaultdict[Signature, list[str]] = defaultdict(list)

    for desc in descriptor_set.file:
        for message in desc.message_type:
            descriptor_map[message.name] = message
        for enum in desc.enum_type:
            descriptor_map[enum.name] = enum

    def get_enum_sig(enum: EnumDescriptorProto) -> frozenset:
        if enum.options.allow_alias: return # Ignore CmdId enums
        return frozenset([e.number for e in enum.value])

    def get_signature(name: str, proto: DescriptorProto | EnumDescriptorProto = None) -> Signature:
        # The TLDR: For signatures, message and oneof types turn into FrozenMultisets of their fields,
        # enums turn into frozensets of their values, and maps turn into NamedTuples of (key, value)
        # Scalar type fields are just the str of their label and type
        # A field of message, enum, map, or oneof type is a NamedTuple of (label_type, signature)
        if name in proto2sig_map:
            return proto2sig_map[name]
        if not proto:
            proto = descriptor_map[name]
           
        if type(proto) == DescriptorProto:
            field_list: list[str | tuple] = []
            oneofs: list[list[str | tuple]] = [[] for _ in range(len(proto.oneof_decl))]

            for nested_type in proto.nested_type:
                nested_name = f"{name}.{nested_type.name}"
                proto2sig_map[nested_name] = get_signature(nested_name, nested_type)

            for enum_type in proto.enum_type:
                if enum_sig := get_enum_sig(enum_type):
                    nested_name = f"{name}.{enum_type.name}"
                    proto2sig_map[nested_name] = enum_sig

            for field in proto.field:
                field_label = ((FieldDescriptorProto.Label.Name(field.label)
                                .removeprefix("LABEL_").lower() + " ")
                                if field.label != FieldDescriptorProto.Label.LABEL_OPTIONAL else "")
                field_type = FieldDescriptorProto.Type.Name(field.type).removeprefix("TYPE_").lower()
                field_type_sig: Signature = None

                if field.HasField("type_name"):
                    type_sig = get_signature(strip_proto_name(field.type_name))
                    if options.getboolean("DEFAULT_EMPTY_TO_BYTES", True) and not type_sig:
                        field_type = "bytes"
                    else:
                        field_type_sig = get_signature(strip_proto_name(field.type_name))
                        if type(field_type_sig) == MapEntry:
                            field_type = "map"

                field_info = f"{field_label}{field_type}"
                if field_type_sig:
                    field_info = FieldTuple(field_info, field_type_sig)

                if field.HasField("oneof_index"):
                    oneofs[field.oneof_index].append(field_info)
                else:
                    field_list.append(field_info)

            for olist in oneofs:
                field_list.append(FieldTuple("oneof", FrozenMultiset(olist)))

            if proto.options.map_entry:
                return MapEntry(*field_list)

            return FrozenMultiset(field_list)

        elif type(proto) == EnumDescriptorProto:
            return get_enum_sig(proto)

    for name, proto in descriptor_map.items():
        sig = get_signature(name, proto)
        proto2sig_map[name] = sig
        sig2proto_map[sig].append(name)

    unique_protos = {sig: proto[0] for sig, proto in sig2proto_map.items() if len(proto) == 1}
    return proto2sig_map, unique_protos

def start_sequential_matching(ref_signatures: dict[str, Signature], ref_proto_list: list[str], 
                              obs_signatures: dict[str, Signature], obs_proto_list: list[str], 
                              exact_matches: dict[str, str]):
    seq_matches: dict[str, str] = {}
    obs_index = 0
    for ref_proto in ref_proto_list:
        if obs_index + 1 >= len(obs_proto_list): break
        if ref_proto not in ref_signatures: continue

        ref_name = f"{to_proto_name(ref_proto)} [{ref_proto_list.index(ref_proto)}]"
        if ref_proto in exact_matches:
            exact_match = exact_matches[ref_proto]
            seq_matches[ref_proto] = exact_match
            match_name = f"{to_proto_name(exact_match)} [{obs_proto_list.index(exact_match)}]"
            print(f"{ref_name} has an exact unique match with {match_name}!")
            continue

        ref_sig = ref_signatures[ref_proto]
        while(True):
            if obs_index + 1 >= len(obs_proto_list): break
            obs_proto = obs_proto_list[obs_index]
            if obs_proto not in obs_signatures:
                obs_index += 1
                continue
            obs_sig = obs_signatures[obs_proto]

            obs_name = f"{to_proto_name(obs_proto)} [{obs_proto_list.index(obs_proto)}]"
            score = compare_sigs(ref_sig, obs_sig)
            if score == 1:
                seq_matches[ref_proto] = obs_proto
                print(f"{ref_name} has an exact match with {obs_name}!")
                break
            
            print(f"{ref_name}:")
            print_sig_tree(ref_sig)
            print(f"{obs_name}:")
            print_sig_tree(obs_sig)
            get_matches(ref_proto, ref_sig, obs_signatures, obs_proto_list)

            print(f"{ref_name} against {obs_name} only scored {colored_percent(score)}")
            keep = input("Keep this as match? (empty to keep, 1 to skip current ref proto, 2 to skip current obs proto): ")
            if keep == "1": break
            elif keep == "2":
                obs_index += 1
                continue
            seq_matches[ref_proto] = obs_proto
            break
    
    with open(OUTPUT_DIR / "seq_matches.json", "w") as f:
        json.dump(seq_matches, f, indent=2)
    print("Finished sequential matching.")

def main():
    load_config()
    ref_descriptor = get_descriptor_set(options["REF_DESCRIPTOR_FILE"])
    ref_proto_list = get_proto_list(options["REF_PROTO_LIST"])
    obs_descriptor = get_descriptor_set(options["OBS_DESCRIPTOR_FILE"])
    obs_proto_list = get_proto_list(options["OBS_PROTO_LIST"])

    ref_signatures, ref_uniques = generate_signatures(ref_descriptor)
    obs_signatures, obs_uniques = generate_signatures(obs_descriptor)
    exact_matches: dict[str, str] = {}
    perfect_mappables: dict[str, str] = {}

    exact_matches_table = sig_proto_table()
    perfect_mappables_table = sig_proto_table()

    for sig, ref_proto in sorted(ref_uniques.items(), key=lambda x: x[1]):
        if sig not in obs_uniques:
            continue
        obs_proto = obs_uniques[sig]
        row = (short_hash(sig), to_proto_name(obs_proto), to_proto_name(ref_proto))
        exact_matches[ref_proto] = obs_proto
        exact_matches_table.add_row(*row)

        if type(sig) == FrozenMultiset and len(sig) != len(sig.distinct_elements()):
            continue
        perfect_mappables[ref_proto] = obs_proto
        perfect_mappables_table.add_row(*row)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Loaded {len(ref_signatures)} reference and {len(obs_signatures)} obfuscated signatures.")
    print("Type help or ? for a list of commands.")

    # I don't like this module honestly but it's good enough, whatever
    class ProtoMatcher(cmd.Cmd):
        prompt = "\n> "

        def do_search(self, text: str):
            "search, s <name>\n" \
            "Search matches for a known proto. " \
            "Will only show matches that meet the provided threshold in the config (default is 50%)."
            text = text.removesuffix(".proto")

            if text in ref_signatures:
                match_sig = ref_signatures[text]
                compare_sigs = obs_signatures
                proto_list = obs_proto_list
            elif text in obs_signatures:
                match_sig = obs_signatures[text]
                compare_sigs = ref_signatures
                proto_list = ref_proto_list
            else:
                print(f"No such proto as {to_proto_name(text)}")
                return
            print_sig_tree(match_sig)
            print(f"Field Count: {len(match_sig)} shallow, {get_sig_rlen(match_sig)} total")

            if text in exact_matches:
                print(f"{to_proto_name(text)} has a unique exact match with "
                      f"{to_proto_name(exact_matches[text])}")
                if text in perfect_mappables:
                    print("This proto is also perfectly re-mappable!")
                return 
            with console.status("Matching...", spinner="monkey", speed=5):
                get_matches(text, match_sig, compare_sigs, proto_list)
        
        do_s = do_search

        def do_uniques(self, text: str):
            "uniques, u <ref|obs, default ref>\n" \
            "Print a list of protos (from reference or obfuscated) with unique signatures."
            u_type = "obfuscated" if text == "obs" else "reference"
            uniques = obs_uniques if text == "obs" else ref_uniques
            print(*[Text.assemble("(", short_hash(sig), ") ",
                Text.from_markup(to_proto_name(proto))) 
                for sig, proto in uniques.items()], sep="\n")
            print(f"Total {u_type} signatures: {len(uniques)}")

        do_u = do_uniques

        def do_exact_matches(self, _):
            "exact_matches, em\n" \
            "Print a table of exact signature matches."
            with open(OUTPUT_DIR / "exact_matches.json", "w") as f:
                json.dump(exact_matches, f, indent=2)
            print(exact_matches_table)
            print(f"Found {len(exact_matches)} unique exact matches from {len(ref_uniques)} "
                  f"unique reference protos ({len(ref_signatures)} total)")

        do_em = do_exact_matches

        def do_perfect_mappables(self, _):
            "perfect_mappables, pm\n" \
            "Print a table of protos that are perfectly re-mappable" \
            "(unique exact matches with all unique types)."
            with open(OUTPUT_DIR / "perfect_mappables.json", "w") as f:
                json.dump(perfect_mappables, f, indent=2)
            print(perfect_mappables_table)
            print(f"Found {len(perfect_mappables)} perfectly re-mappable protos "
                  f"from {len(exact_matches)} unique exact matches.")
            # BIG TODO: actually do the auto-remapping programmatically

        do_pm = do_perfect_mappables

        def do_sequential_match(self, _):
            "sequential_match, sm\n" \
            "Start a sequential matching session using the provided proto lists."
            start_sequential_matching(ref_signatures, ref_proto_list, obs_signatures, obs_proto_list, exact_matches)

        do_sm = do_sequential_match

        def do_reload(self, _):
            "reload, r\n" \
            "Reload the config from file."
            load_config()
            print("Config reloaded.")

        do_r = do_reload

        def do_quit(self, _):
            "quit, q\n" \
            "Exit the script."
            exit(0)

        do_q = do_quit

    ProtoMatcher().cmdloop()

if __name__ == '__main__': main()