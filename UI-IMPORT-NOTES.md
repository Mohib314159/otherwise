# Hero V3 archive for UI review

Source: Otherwise-UI-Flagship-HeroV3.zip, supplied by the user.

This branch overlays the archive onto main at ff15ca42aaa6a294bc6e1b2ddca9b55638ddc686. Files absent from the archive are retained. Archive contents are supplied for review, not validated for merging.

Claude: take the desired UI changes from web/ and review tests/test_pwa.py. Do not merge this branch wholesale: the archive also contains older backend, dependency, deployment, and documentation files. Preserve current main versions of those files. Review compatibility with air pages and current feature flags, then test desktop and mobile before merging selected changes.

No application tests or browser validation were run for this import. Main has not been modified by this task.
