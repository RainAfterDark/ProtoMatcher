# Proto Matcher

Simple tool for fuzzy matching obfuscated protobuf definitions with existing reference ones.

## Usage

- `pip install -r requirements.txt`
- Compile a descriptor file for the protos you want to match (using `protoc` and the `--descriptor_set_out` option, see examples in `/ref_data`)
- Provide a declaration list for protos (in `.json`, for sequential matching)
- Run the script and fill in the necessary file paths (you can modify the generated `config.ini` later)

## Commands

- `search, s <name>`
    
    Search matches for a known proto. Will only show matches that meet the provided threshold in the config (default is 50%).

- `uniques, u <ref|obs, default ref>`

    Print a list of protos (from reference or obfuscated) with unique signatures.

- `exact_matches, em`

    Print a table of exact signature matches.

- `perfect_mappables, pm`

    Print a table of protos that are perfectly re-mappable (unique exact matches with all unique types).

- `sequential_match, sm`

    Start a sequential matching session using the provided proto lists. (Not so great for now, console is too limited for this and it's better to visualize it with some kind of frontend)

- `reload, r`

    Reload the config from file.

- `quit, q`

    Exit the script.