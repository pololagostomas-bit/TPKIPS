# Collaboration & Sharing

## Track — git tracking control

Toggle whether `.context/` is tracked in the project's git repo:
```bash
amem track              # show current tracking status
amem track --enable     # add .context/ to project git
amem track --disable    # remove .context/ from project git
```

## Push / Pull — remote sync

Sync `.context/` to a separate remote (independent of project git):
```bash
amem push                      # push to configured remote
amem push --remote <url>       # push to specific remote
amem pull                      # pull from configured remote
amem pull --remote <url>       # clone/pull from specific remote
```

## Share / Import — portable snapshots

Generate a portable snapshot of your context for sharing with teammates or other agents:
```bash
amem share                     # generate snapshot file
amem share --output path.json  # custom output path
```

Import a shared snapshot:
```bash
amem import <file>             # import shared snapshot into .context/
```
