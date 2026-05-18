# 1C platform distributions

Put local 1C Linux DEB packages or archives here. Files in this directory are
ignored by git except this README.

Recommended layout:

```text
dist/
  8.3.27.1644/
    amd64/
      1c-enterprise-8.3.27.1644-common_8.3.27-1644_amd64.deb
      1c-enterprise-8.3.27.1644-common-nls_8.3.27-1644_amd64.deb
      1c-enterprise-8.3.27.1644-server_8.3.27-1644_amd64.deb
      1c-enterprise-8.3.27.1644-server-nls_8.3.27-1644_amd64.deb
      1c-enterprise-8.3.27.1644-client_8.3.27-1644_amd64.deb
      1c-enterprise-8.3.27.1644-client-nls_8.3.27-1644_amd64.deb
      # thin-client packages may be present, but the exporter skips them
      # because Designer requires thick client and thin-client conflicts
      # with common/server packages in 8.3.27.
    arm64/
      *.deb
```

Archives such as `deb64_8_3_27_1644.tar.gz` are also accepted.
