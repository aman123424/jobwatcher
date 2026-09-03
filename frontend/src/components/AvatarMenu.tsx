import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { getInitials } from "../utils/initials";

interface AvatarMenuProps {
  name: string;
}

/**
 * The round initials button (see getInitials()) now opens a dropdown
 * instead of navigating straight to /profile (Aman's sketch, 2026-09-03)
 * - "View Profile" and "Logout" both live here now, so the header no
 * longer needs its own separate Log out button next to it.
 */
export function AvatarMenu({ name }: AvatarMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const { logout } = useAuth();

  // Closes the dropdown on a click anywhere outside it - only
  // listens while actually open, so this isn't one more permanent
  // document-wide listener for the whole app's lifetime.
  useEffect(() => {
    if (!open) return;
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  function handleViewProfile() {
    setOpen(false);
    navigate("/profile");
  }

  function handleLogout() {
    setOpen(false);
    logout();
    navigate("/login");
  }

  return (
    <div className="avatar-menu" ref={containerRef}>
      <button
        type="button"
        className="avatar-button"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={`${name}'s account menu`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={name}
      >
        {getInitials(name)}
      </button>

      {open && (
        <div className="avatar-dropdown" role="menu">
          <button type="button" className="avatar-dropdown-item" role="menuitem" onClick={handleViewProfile}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="8" r="3.6" stroke="currentColor" strokeWidth="1.6" />
              <path
                d="M4.5 20c1.2-3.8 4.4-6 7.5-6s6.3 2.2 7.5 6"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
            View Profile
          </button>
          <button type="button" className="avatar-dropdown-item" role="menuitem" onClick={handleLogout}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M9 4H5.5A1.5 1.5 0 0 0 4 5.5v13A1.5 1.5 0 0 0 5.5 20H9M15 16l4-4-4-4M19 12H9"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Logout
          </button>
        </div>
      )}
    </div>
  );
}
