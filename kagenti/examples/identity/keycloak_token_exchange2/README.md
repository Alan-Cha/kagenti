## Create Cluster

```sh
podman machine rm -f
podman machine init -m 4096 --rootful=true
podman machine start
```

```sh
export KIND_EXPERIMENTAL_PROVIDER=podman
```

## Start KeyCloak

```sh
docker run -p 8080:8080 -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin quay.io/keycloak/keycloak:26.2.5 start-dev
```