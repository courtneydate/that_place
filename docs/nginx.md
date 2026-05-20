# Nginx Multi-Site Setup Guide

How to host multiple websites on a single server using Nginx as a reverse proxy,
alongside a running Django application (That Place).

---

## Prerequisites

- Ubuntu 22.04 / Debian 12 server (adapt paths for other distros)
- A domain name for each site, with DNS A records pointing to your server's IP
- That Place already running via Gunicorn on a local port (e.g. `127.0.0.1:8000`)
- Root or sudo access

---

## 1. Install Nginx

```bash
sudo apt update
sudo apt install nginx -y
sudo systemctl enable nginx
sudo systemctl start nginx
```

Verify it's running:

```bash
sudo systemctl status nginx
```

---

## 2. Understand the Config Structure

Nginx on Debian/Ubuntu uses this layout:

```
/etc/nginx/
├── nginx.conf                  # Global config — rarely edited
├── sites-available/            # One file per site (disabled until linked)
│   ├── that-place
│   ├── site1.com
│   └── site2.com
└── sites-enabled/              # Symlinks to sites-available (active sites)
    ├── that-place -> ../sites-available/that-place
    └── site1.com  -> ../sites-available/site1.com
```

The pattern is: write a config in `sites-available`, then symlink it into
`sites-enabled` to activate it.

---

## 3. Configure That Place (Django App)

Create `/etc/nginx/sites-available/that-place`:

```nginx
server {
    listen 80;
    server_name app.yourdomain.com;

    # Static files served directly by Nginx
    location /static/ {
        alias /srv/that-place/staticfiles/;
    }

    # Media files (if using local storage for dev; use S3 in production)
    location /media/ {
        alias /srv/that-place/media/;
    }

    # Everything else proxied to Gunicorn
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/that-place /etc/nginx/sites-enabled/
```

---

## 4. Configure a Static Site

For each static site, create a directory for the files and an Nginx config.

### 4a. Create the web root

```bash
sudo mkdir -p /var/www/site1.com
sudo chown -R $USER:$USER /var/www/site1.com
```

Drop your HTML/CSS/JS files in `/var/www/site1.com/`. The entry point should
be `index.html`.

### 4b. Create `/etc/nginx/sites-available/site1.com`

```nginx
server {
    listen 80;
    server_name site1.com www.site1.com;

    root /var/www/site1.com;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }

    # Cache static assets aggressively
    location ~* \.(css|js|jpg|jpeg|png|gif|ico|svg|woff2)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/site1.com /etc/nginx/sites-enabled/
```

Repeat steps 4a and 4b for each additional static site, replacing `site1.com`
with the relevant domain.

---

## 5. Contact Form (via Web3Forms)

For static sites that need a contact form, use [Web3Forms](https://web3forms.com)
— no backend required.

1. Sign up at web3forms.com and get a free access key.
2. Add this form to your HTML (replace `YOUR_ACCESS_KEY`):

```html
<form action="https://api.web3forms.com/submit" method="POST">
    <input type="hidden" name="access_key" value="YOUR_ACCESS_KEY">
    <input type="hidden" name="subject" value="New contact form submission">

    <label>Name</label>
    <input type="text" name="name" required>

    <label>Email</label>
    <input type="email" name="email" required>

    <label>Message</label>
    <textarea name="message" required></textarea>

    <button type="submit">Send</button>
</form>
```

Submissions are emailed to the address associated with your Web3Forms account.
No server changes needed.

### Alternative: Route contact forms through That Place's Django backend

If you want full control, add a `contact` app to Django that sends email via SES,
then point the form's `action` to `https://app.yourdomain.com/api/v1/contact/`.

---

## 6. SSL with Let's Encrypt

Run this for every domain (repeat for each site):

```bash
sudo apt install certbot python3-certbot-nginx -y

# Issue and auto-configure SSL for a domain
sudo certbot --nginx -d app.yourdomain.com

sudo certbot --nginx -d site1.com -d www.site1.com
sudo certbot --nginx -d site2.com -d www.site2.com
```

Certbot edits your Nginx configs automatically to add HTTPS and redirect HTTP → HTTPS.
Certificates renew automatically via a systemd timer — verify with:

```bash
sudo certbot renew --dry-run
```

---

## 7. Test and Reload

Always test the config before reloading:

```bash
sudo nginx -t
```

If the test passes:

```bash
sudo systemctl reload nginx
```

`reload` applies the new config without dropping active connections.
Use `restart` only if `reload` fails.

---

## 8. Useful Commands

| Task | Command |
|---|---|
| Test config | `sudo nginx -t` |
| Reload config | `sudo systemctl reload nginx` |
| View error log | `sudo tail -f /var/log/nginx/error.log` |
| View access log | `sudo tail -f /var/log/nginx/access.log` |
| Per-site access log | `sudo tail -f /var/log/nginx/site1.com.access.log` |
| List enabled sites | `ls -la /etc/nginx/sites-enabled/` |
| Disable a site | `sudo rm /etc/nginx/sites-enabled/site1.com` |

---

## 9. Per-Site Access Logs (Optional but Recommended)

Add these lines inside each `server` block to get separate log files per site:

```nginx
access_log /var/log/nginx/site1.com.access.log;
error_log  /var/log/nginx/site1.com.error.log;
```

---

## 10. Future: Adding a Shop

When you're ready to add a shop, two paths:

**Stripe Checkout (simplest):** No new backend. Create a product in the Stripe
dashboard, redirect users to a Stripe-hosted checkout URL. Add a new server
block only if the shop lives on its own domain.

**Self-hosted (Medusa.js):** Run Medusa on a local port (e.g. `127.0.0.1:9000`)
and proxy to it exactly like the Django app in step 3.

```nginx
server {
    listen 80;
    server_name shop.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
