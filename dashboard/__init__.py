"""The muxtopus dashboard.

    deck_status.py     the SHELL: argv, the terminal, the main loop
    dashboard.core     constants, paths, the account profile, the formatters
    dashboard.data     every reader of the machine and of the watchdog's files
    dashboard.schedules  a schedule entry as data
    dashboard.menulayout  a menu panel drawn at an exact height
    dashboard.app      the App object, the menu engine and the registries
    dashboard.views.*  one screen each, DISCOVERED rather than listed
    dashboard.menus.*  one menu kind each, likewise

The package is imported straight out of the checkout -- the entry script's
directory is on sys.path, so there is no install step and no path hack. See
docs/dashboard-views.md for what a new view has to provide.
"""
