# Cloud-init — first-boot VM prep

Paste one of these into your cloud provider **User data** field on instance create. They install git/python and create the nanoclaw workspace path. **Bootstrap code** still comes from `scripts/dev_bootstrap.sh` on your laptop.

## Files

| File | Use |
|------|-----|
| [`generic.yaml`](generic.yaml) | Any Ubuntu 22.04/24.04 (GCP, AWS, Azure, Oracle) |
| [`oracle-ubuntu.yaml`](oracle-ubuntu.yaml) | Same as generic — Oracle AMD micro |

## Provider notes

### Oracle Cloud

1. Create VM → **Advanced options** → **Cloud-init script**
2. Paste contents of `oracle-ubuntu.yaml`
3. SSH key: same as `~/.nanoclaw/config.yaml` → `ssh_key`
4. After boot: `./scripts/dev_preflight.sh --host NEW_IP`
5. Fund dev wallet, then `./scripts/dev_bootstrap.sh --host NEW_IP --secrets ~/.nanoclaw/secrets.dev.env`

### GCP / AWS / Azure

Use `generic.yaml` in metadata user-data. Default user may be `ubuntu` (GCP) or `ec2-user` — set `--user` on bootstrap scripts if different.

## After cloud-init

```bash
cp infra/config.yaml.example ~/.nanoclaw/config.yaml
# set dev_host to NEW_IP

./scripts/dev_preflight.sh --role dev
./scripts/dev_bootstrap.sh --role dev --branch V4-play --seed-usd 50 \
  --secrets ~/.nanoclaw/secrets.dev.env
```

## Teardown

```bash
./scripts/dev_destroy.sh --role dev --wipe
```

Wallet funds remain on-chain; only VM state is removed.
