//! Bounded dark appearance configuration. No CSS or font URLs are accepted.
use std::collections::BTreeMap;

const DEFAULTS: &[(&str, &str)] = &[
    ("background", "#08090a"),
    ("surface", "#0d0e10"),
    ("raised", "#131416"),
    ("hover", "#17181b"),
    ("selected", "#1c1d20"),
    ("border", "#25262a"),
    ("foreground", "#eeeeef"),
    ("secondary", "#c5c6cc"),
    ("muted", "#9a9ca5"),
    ("accent", "#aeb4c6"),
];

fn luminance(value: &str) -> f64 {
    let channels: Vec<f64> = (1..7)
        .step_by(2)
        .map(|i| {
            let c = u8::from_str_radix(&value[i..i + 2], 16).unwrap() as f64 / 255.;
            if c <= 0.04045 {
                c / 12.92
            } else {
                ((c + 0.055) / 1.055).powf(2.4)
            }
        })
        .collect();
    channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
}
fn contrast(a: &str, b: &str) -> f64 {
    let (a, b) = (luminance(a), luminance(b));
    (a.max(b) + 0.05) / (a.min(b) + 0.05)
}

/// Empty means no customization: existing preset CSS is untouched. Invalid palettes
/// reject atomically, so a partial change cannot leave unreadable foreground/background.
pub fn stylesheet(input: &BTreeMap<String, String>) -> Result<String, &'static str> {
    if input.is_empty() {
        return Ok(String::new());
    }
    let mut values: BTreeMap<&str, &str> = DEFAULTS.iter().copied().collect();
    let mut font = "Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,\"Segoe UI\",sans-serif";
    for (key, value) in input {
        if key == "font" {
            font = match value.as_str() {
                "system" => font,
                "mono" => "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace",
                _ => return Err("font must be system or mono"),
            };
        } else if values.contains_key(key.as_str()) {
            if value.len() != 7
                || !value.starts_with('#')
                || !value.as_bytes()[1..].iter().all(u8::is_ascii_hexdigit)
            {
                return Err("colors must be six-digit hex");
            }
            values.insert(key, value);
        } else {
            return Err("unknown appearance token");
        }
    }
    for surface in ["background", "surface", "raised", "hover", "selected"] {
        // Existing semantic warning/error colors are designed for dark surfaces.
        if luminance(values[surface]) > 0.035 {
            return Err("appearance requires dark surfaces");
        }
        for text in ["foreground", "secondary", "muted"] {
            if contrast(values[text], values[surface]) < 4.5 {
                return Err("text contrast must be at least 4.5:1");
            }
        }
        if contrast(values["accent"], values[surface]) < 3. {
            return Err("focus contrast must be at least 3:1");
        }
    }
    let on_accent =
        if contrast("#000000", values["accent"]) >= contrast("#ffffff", values["accent"]) {
            "#000000"
        } else {
            "#ffffff"
        };
    // Outrank :root[data-theme] even when its bundled stylesheet loads later.
    let mut css = String::from(":root:root:root {");
    for (key, value) in &values {
        css.push_str(&format!("--appearance-{key}:{value};"));
    }
    css.push_str(&format!(
        "--appearance-font:{font};--appearance-on-accent:{on_accent};font-family:{font};"
    ));
    for (existing, token) in [
        ("bg", "background"),
        ("panel", "surface"),
        ("panel-raised", "raised"),
        ("hover", "hover"),
        ("active", "selected"),
        ("border", "border"),
        ("border-soft", "border"),
        ("text-primary", "foreground"),
        ("text-secondary", "secondary"),
        ("text-muted", "muted"),
        ("text-subtle", "muted"),
        ("focus", "accent"),
    ] {
        css.push_str(&format!("--{existing}:var(--appearance-{token});"));
    }
    css.push_str("background:var(--bg);color:var(--text-primary);}");
    css.push_str(":root:root:root :is(button,a,input,textarea,select,summary):focus-visible{outline:2px solid var(--appearance-accent);outline-offset:2px;} :root:root:root input{accent-color:var(--appearance-accent);}");
    Ok(css)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn config(items: &[(&str, &str)]) -> BTreeMap<String, String> {
        items
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }
    #[test]
    fn defaults_are_untouched() {
        assert_eq!(stylesheet(&BTreeMap::new()), Ok(String::new()));
    }
    #[test]
    fn partial_config_and_font() {
        let css = stylesheet(&config(&[("accent", "#1EFF5A"), ("font", "mono")])).unwrap();
        assert!(css.contains("--appearance-accent:#1EFF5A"));
        assert!(css.contains("--appearance-background:#08090a"));
        assert!(css.contains("--appearance-on-accent:#000000"));
        assert!(css.contains("ui-monospace"));
    }
    #[test]
    fn rejects_invalid_and_unreadable() {
        for items in [
            vec![("accent", "red;}")],
            vec![("font", "url(x)")],
            vec![("unknown", "#000000")],
            vec![("background", "#ffffff")],
            vec![("foreground", "#101010")],
            vec![("accent", "#101010")],
            vec![("muted", "#xyzxyz")],
        ] {
            assert!(stylesheet(&config(&items)).is_err());
        }
    }
    #[test]
    fn changing_token_changes_output() {
        let a = stylesheet(&config(&[("accent", "#1EFF5A")])).unwrap();
        let b = stylesheet(&config(&[("accent", "#80ccff")])).unwrap();
        assert_ne!(a, b);
    }
}
