# Command line

```console
$ python -m humanize naturalsize 8589934592
8.6 GB
$ humanize naturalsize --binary 8589934592
8.0 GiB
$ humanize intcomma 1234567
1,234,567
$ humanize intword 1200000
1.2 million
$ humanize naturaldelta 3600
an hour
```

`naturalsize` also accepts `--gnu` and `--format`. Errors go to stderr with a non-zero exit.
