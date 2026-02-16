import jwt

def get_client_id() -> str:
    """
    Read the SVID JWT from file and extract the client ID from the "sub" claim.
    This returns the SPIFFE ID of the workload.
    """
    jwt_file_path = "/opt/jwt_svid.token"
    content = None
    try:
        with open(jwt_file_path, "r") as file:
            content = file.read()
    except FileNotFoundError:
        print(f"Error: The file {jwt_file_path} was not found.")
        raise
    except Exception as e:
        print(f"An error occurred: {e}")
        raise

    if content is None or content.strip() == "":
        raise Exception("No content read from SVID JWT.")

    # Decode JWT to get client ID (SPIFFE ID from "sub" claim)
    decoded = jwt.decode(content, options={"verify_signature": False})
    if "sub" not in decoded:
        raise Exception('SVID JWT does not contain a "sub" claim.')
    return decoded["sub"]

def get_jwt_svid() -> str:
    """
    Read and return the JWT-SVID token.
    This token can be used as a client_assertion for OAuth 2.0 authentication.
    """
    jwt_file_path = "/opt/jwt_svid.token"
    try:
        with open(jwt_file_path, "r") as file:
            return file.read().strip()
    except FileNotFoundError:
        print(f"Error: The file {jwt_file_path} was not found.")
        raise
    except Exception as e:
        print(f"An error occurred: {e}")
        raise