# Keycloak Kagenti user realm + User 

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

You can access Keycloak at [http://localhost:8080](http://localhost:8080).

The username and password are `admin`.

## Set up user realm and test user

```sh
python keycloak_setup.py
```

The `user` realm should be created along with a `test` user with the password: `test_password`.

# Client Registration

## Docker

### Start Keycloak

```sh
docker run -p 8080:8080 -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=admin quay.io/keycloak/keycloak:26.2.5 start-dev
```

You can access Keycloak at [http://localhost:8080](http://localhost:8080).

The username and password are `admin`.

### Build client registration image

```sh
docker build -t client_registration .
```

### Run client registration image

```sh
docker run \
  -e KEYCLOAK_URL=http://host.docker.internal:8080 \
  -e KEYCLOAK_REALM=master \
  -e KEYCLOAK_ADMIN_USERNAME=admin \
  -e KEYCLOAK_ADMIN_PASSWORD=admin \
  -e CLIENT_NAME=client_registration_docker \
  client_registration
```

You will see that `client_registration_docker` client will be created in the `master` realm.

## Kubernetes

### Start Minikube

```sh
minikube start
```

### Start Keycloak

```sh
kubectl apply -f keycloak.yaml
```

### Port forward Keycloak

```sh
kubectl port-forward service/keycloak 8080:8080
```

You can access Keycloak at [http://localhost:8080](http://localhost:8080).

The username and password are `admin`.

### Build client registration image

```sh
eval $(minikube docker-env)
```

```sh
docker build -t client_registration .
```

### Create Kubernetes secret

```sh
kubectl create secret generic keycloak-secret \
  --from-literal=KEYCLOAK_URL=http://keycloak:8080 \
  --from-literal=KEYCLOAK_REALM=master \
  --from-literal=KEYCLOAK_ADMIN_USERNAME=admin \
  --from-literal=KEYCLOAK_ADMIN_PASSWORD=admin \
  --from-literal=CLIENT_NAME=client_registration_k8s
```

### Run client registration job

```sh
kubectl apply -f client_registration.yaml
```

You will see that `client_registration_k8s` client will be created in the `master` realm.