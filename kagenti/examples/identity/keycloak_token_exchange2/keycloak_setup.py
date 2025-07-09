base_url = "http://localhost:8080"
admin_username = "admin"
admin_password = "admin"
user_realm_name = "user"
client_realm_name = "client"

from keycloak import KeycloakAdmin, KeycloakPostError

keycloak_admin = KeycloakAdmin(
            server_url=base_url,
            username=admin_username,
            password=admin_password,
            realm_name=user_realm_name,
            user_realm_name='master')

# Create the user realm
try:
    keycloak_admin.create_realm(
        payload={
            "realm": user_realm_name,
            "enabled": True
        },
        skip_exists=True
    )

    print(f'Created realm "{user_realm_name}"')
except KeycloakPostError as e:
    print(f'Realm "{user_realm_name}" already exists')

test_user_name = "test"

# Add test user
try:
    keycloak_admin.create_user({
        "username": test_user_name,
        "firstName": test_user_name,
        "lastName": test_user_name,
        "email": "test@test.com",
        "emailVerified": True,
        "enabled": True,
        "credentials": [{"value": "test_password", "type": "password",}]
    })

    print(f'Created user "{test_user_name}"')
except KeycloakPostError as e:
    print(f'User "{test_user_name}" already exists')

# Create the client realm
try:
    keycloak_admin.create_realm(
        payload={
            "realm": client_realm_name,
            "enabled": True
        },
        skip_exists=True
    )

    print(f'Created realm "{client_realm_name}"')
except KeycloakPostError as e:
    print(f'Realm "{client_realm_name}" already exists')