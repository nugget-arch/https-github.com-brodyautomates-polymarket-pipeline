"""
otc_lab — quantitative research platform for OTC binary options.

Purpose: determine, with honest statistics, whether any real and persistent
edge exists in OTC binary-options data. A valid outcome of this software is
the conclusion "NO SE HA DEMOSTRADO UNA VENTAJA ESTADÍSTICA OPERABLE".

Hard constraints (by design, not by accident):
  * Historical data + paper trading / shadow mode only.
  * Live execution is DISABLED. There is no PocketOption connector, no
    reverse-engineered endpoint, no browser automation, no credential storage.
  * `BrokerAdapter` is an abstract seam for a hypothetical FUTURE official,
    documented API — nothing else.
  * No martingale / loss-recovery sizing anywhere. The risk manager enforces
    that stakes never increase as a function of previous losses.
"""

__version__ = "0.1.0"

EXECUTION_ENABLED: bool = False
"""Global flag. Hard-coded False: this codebase does not place real orders."""
