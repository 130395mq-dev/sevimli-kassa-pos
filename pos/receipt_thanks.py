"""
Chek pastidagi salom bar: «UYDAGILARGA BIZDAN SALOM!» + Instagram.
ESC/POS raster (GS v 0) — oq fon, qora yozuv: qora nuqta kam, printer
kallagi kam qiziydi. Oldindan tayyorlangan; zlib + base64 bilan saqlanadi.
"""

import base64
import zlib


def _unpack(data: str) -> bytes:
    return zlib.decompress(base64.b64decode(data))


#: 80 mm qog'oz: 576x196 nuqta
THANKS_80 = _unpack(
    "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"
)

#: 58 mm qog'oz: 384x129 nuqta
THANKS_58 = _unpack(
    "eNrt2EFrIzcUAGBNVVaXxdrjHrxWf0L25kBqFfaPLPQPbFgoDh1WY3zwpTT01gWT/IUet6dVMOzc"
    "kj+wFA2GznEVcpFBSH3SjLMeO1uslkChMYlNyGfz/N7T04ye/XCADtAE3fuD+YSHQUikeIcylRIM"
    "KXCR4jOJ076tfJTmX6b6x2n+4MF/SSb6YaIfJHmKaZJnkzLFv2TFstjfZ5rJ4wSPDZNDueFpsdL0"
    "ClanQVQzIhFHwiCmkG28parf9cbQUy8zi7iLvhAOCYtcEw/4xy+73jLqFbbIRy/AZ95mrXdU97Z8"
    "zulUY5vZXuNzjk2/9cgT/WjLj0Z0YojL9FfBe5kzrL7Gfu3Ntuc5PBGHFVp7eFl7MTPkm65nlhY5"
    "OWv9TeuvWj+1GHU9NeDpOYk+u1E5oxKRq1ClTPHFrteNl6718H1s6zVfOrTlSfS09ZUSNvhZ0ZS3"
    "coh2PVbgGZ1FjystDHj4M5aLXXso4Z1eDVpvqTxqPZTLQ0nu8H7ReG/yNwS8V236fSHkZ08ab3jr"
    "CXgOnq299YXf+HxyocFPwF/otYf6rj2k38uOXwY/1TmubPAQWk6n5miU6fBvvnCi4zG0poJgc6xC"
    "f/pPwU+8XfvKiWrTZ14GL8dQyujRUU6ksEcoekgnr/zmehQIvEMm02F9eY9G4JnKkYnpM/79td9/"
    "/UJ6Er3wq/09nToe9uq9/YVP8kz590mfr4VP8ibNE8uTPPas672GYaihF1nB4QKHGPQGCks0rFE5"
    "Dt1yuuVt9BYxySfwLhid4LltPfLllnfRO8Sj5w558MIRmOPgn4i6682IFlgbHvyFQvkgestb/1T4"
    "XU+UYYVQwY8h4sJkhs0sj57f4amEAQe+uvWatn7O7vZEnkSfo6xu/Mcfg/+J+p38FAxGnFzp0bUK"
    "i6eWBmtS/hH9Jdn2EApHt57r6BUpL18H/wH7nXwWb4LXenQC3uJF469ugq+zO+KHxQtTyARPHVmo"
    "xi+D/77Y9owWtvXfKshO9BB/Gf2xFDt+YoKHicNhonHidcwP+HApo/iOn2pk6BQ8bNIIttbGLxbB"
    "98ehALbjZwqeg6cKfdd4qC94iGfwdNtzegoeJvIo+PGIIRP7R+LgCaJdH/vTeBc8bHjCgfcW+rPx"
    "uCDNvUKn/0GQYhC9HaCxt9D/jUcSb3kdPewYbAQbMNUjlMO79dqjUDCdcj0GXqV4KJhM8TzRQwHS"
    "rj+bdtjb4yad+18PN+l5uB/5P/hsv5t3+U/9Q/7/gz6TKGvuSdWuV2HIfx5OO179rY9X+gleqduQ"
    "vuDr4YjV6vW8rC7Hw0weGNZ/Vh5WZb+eqT+X5cKSnti8/62tOK+NPy9X3g6z018cvzws/XXJfGlc"
    "fXqz48+OZ+iwPoPf+RCztx+OwZ8dl4MTOdSf+q8U6ZGO//kVIavFGVnVc4Sfv5Wift740mjLDPjO"
    "+UDd44SuFnO6Kvvgf7WiPi774efKqMYPuh7PeoeLee8w+t96r0jrL4fK9RH4o65/Meud1PPeSdmH"
    "+K974xdV68eqHjxR9dm468XsyvgYD+TnwvFFdRvP8lSbpevmp8dx+e71nPwevESWTS4aX75TVanG"
    "1aXYPX8g7dmdkvv152yzf/bwbrM/9/D5w3z41/6+z0tTz29Tz4dTz59Tz7eTz8/v+fEXQErfrg=="
)
