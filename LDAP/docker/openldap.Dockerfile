FROM osixia/openldap:1.5.0

# Seed demo directory entries that match LDAP/main.py search OUs.
COPY seed/50-hpd-seed.ldif /container/service/slapd/assets/config/bootstrap/ldif/custom/50-hpd-seed.ldif
